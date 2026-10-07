import json
from asyncio import get_running_loop, wait_for
from html import escape
from urllib.parse import urlparse

from niquests import AsyncSession
from pyrogram.enums import ButtonStyle, ChatType
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from .. import LOGGER, bot_loop, sudo_users, user_data
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import delete_message, edit_message, send_message

def _is_auth(user_id):
    return user_id == Config.OWNER_ID or user_id in sudo_users or bool(user_data.get(user_id, {}).get('SUDO'))


def _clean_domain(value):
    value = str(value or '').strip().lower()
    value = value.removeprefix('https://').removeprefix('http://').split('/', 1)[0]
    value = value.split(':', 1)[0]
    return value.removeprefix('www.').strip('.')


def _clean_api(value):
    value = str(value or '').strip()
    if not value.startswith(('http://', 'https://')):
        return ''
    if '{url}' in value:
        return value
    if 'url=' in value:
        return value if value.endswith(('=', '&')) else value + ('&' if '?' in value else '&')
    return value + ('&url=' if '?' in value else '?url=')


def _normalize(items):
    out = []
    if isinstance(items, dict):
        items = [{"domain": k, "api": v} for k, v in items.items()]
    for item in items or []:
        if isinstance(item, dict):
            domain = _clean_domain(item.get('domain'))
            api = _clean_api(item.get('api'))
            if domain and api:
                out.append({'domain': domain, 'api': api})
    return out


def _personal(user_id):
    return _normalize(user_data.get(user_id, {}).get('DLAPI', []))


def _global():
    return _normalize(user_data.get(Config.OWNER_ID, {}).get('DLAPI_GLOBAL', []))


def _set_personal(user_id, items):
    update_user_ldata(user_id, 'DLAPI', _normalize(items))


def _set_global(items):
    update_user_ldata(Config.OWNER_ID, 'DLAPI_GLOBAL', _normalize(items))


def get_api_for_url(url, user_id):
    try:
        host = urlparse(url if '://' in url else 'https://' + url).hostname or ''
    except Exception:
        return None
    host = host.lower().removeprefix('www.').strip('.')
    personal = _personal(user_id)
    global_items = _global()
    # Personal/alone configuration wins over global configuration for the same domain.
    for item in personal + global_items:
        domain = item['domain']
        if host == domain or host.endswith('.' + domain):
            return item['api']
    return None


def build_api_url(template, source_url):
    if '{url}' in template:
        return template.replace('{url}', source_url)
    return template + source_url


def _find_download_url(value, key_hint=''):
    if isinstance(value, dict):
        priority = ('download', 'download_url', 'direct', 'direct_url', 'url', 'link', 'file')
        for key in priority:
            if key in value:
                found = _find_download_url(value[key], key)
                if found:
                    return found
        for key, child in value.items():
            found = _find_download_url(child, str(key))
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_download_url(child, key_hint)
            if found:
                return found
    elif isinstance(value, str) and value.startswith(('http://', 'https://')):
        low = key_hint.lower()
        if any(x in low for x in ('download', 'direct', 'file', 'url', 'link')):
            return value
    return None


async def resolve_dlapi(url, user_id):
    template = get_api_for_url(url, user_id)
    if not template:
        return None
    api_url = build_api_url(template, url)
    try:
        async with AsyncSession() as session:
            response = await session.get(api_url, timeout=60)
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = json.loads(response.text)
        direct = _find_download_url(data)
        if direct:
            LOGGER.info(f'DLAPI resolved {url} -> {direct}')
            return direct
        LOGGER.warning(f'DLAPI returned no download URL for {url}: {data!r}')
    except Exception as e:
        LOGGER.error(f'DLAPI request failed for {url}: {e}')
    return None


def _menu(user_id, auth=False):
    personal = _personal(user_id)
    global_items = _global() if auth else []
    text = '<b>🔗 Download API Configuration</b>\n\n'
    text += '<blockquote>Configure <code>domain=API</code>. Example:\n<code>gdflix.com=https://ddl-y1lj.onrender.com/api/gdflix?url=</code>\n\n'
    text += 'Configured APIs are matched automatically by domain when a link is processed.</blockquote>\n\n'
    buttons = ButtonMaker()
    if auth:
        text += '<b>🌐 Global APIs</b> <i>(available to all users)</i>\n'
        if global_items:
            for i, item in enumerate(global_items):
                text += f'• <code>{escape(item["domain"])}</code> → <code>{escape(item["api"])}</code>\n'
                buttons.data_button(f'🗑️ Global {i + 1}', f'dlapi del g {i}')
        else:
            text += '<i>None configured.</i>\n'
        text += '\n<b>👤 Alone APIs</b> <i>(only for this auth user)</i>\n'
    else:
        text += '<b>👤 My APIs</b>\n'
    if personal:
        for i, item in enumerate(personal):
            text += f'• <code>{escape(item["domain"])}</code> → <code>{escape(item["api"])}</code>\n'
            buttons.data_button(f'🗑️ Alone {i + 1}', f'dlapi del p {i}')
    else:
        text += '<i>None configured.</i>\n'
    buttons.data_button('➕ Add API', 'dlapi add p', position='header')
    if auth:
        buttons.data_button('🌐 Add Global', 'dlapi add g', position='header')
    buttons.data_button('🔄 Refresh', 'dlapi refresh', position='footer')
    buttons.data_button('❌ Close', 'dlapi close', position='footer', style=ButtonStyle.DANGER)
    return text, buttons.build_menu(2)


async def _input_api(client, query, scope):
    user_id = query.from_user.id
    buttons = ButtonMaker()
    buttons.data_button('❌ Cancel', 'dlapi cancel', position='footer', style=ButtonStyle.DANGER)
    label = 'Global' if scope == 'g' else 'Alone'
    prompt = (
        f'<b>➕ Add {label} Download API</b>\n\n'
        '<blockquote>Send one configuration in this exact format:\n'
        '<code>gdflix.com=https://ddl-y1lj.onrender.com/api/gdflix?url=</code>\n\n'
        'The API must return JSON containing an HTTP/HTTPS download URL.\n'
        'You can add unlimited configurations.</blockquote>\n\n'
        '<i>Waiting for your input… 60 sec</i>'
    )
    await query.answer()
    await edit_message(query.message, prompt, buttons.build_menu(1))
    future = bot_loop.create_future() if bot_loop.is_running() else get_running_loop().create_future()

    def filt(_, __, event):
        return bool(event.from_user and event.from_user.id == user_id and event.chat and event.chat.type == ChatType.PRIVATE and event.text)

    async def handler(_, msg):
        if not future.done():
            future.set_result(msg)

    h = client.add_handler(MessageHandler(handler, filters=create(filt)), group=-1)
    try:
        msg = await wait_for(future, timeout=60)
        raw = msg.text.strip()
        await delete_message(msg)
        if '=' not in raw:
            await send_message(query.message, '<blockquote>❌ Invalid format. Use <code>domain=https://api...?url=</code>.</blockquote>')
        else:
            domain, api = raw.split('=', 1)
            domain = _clean_domain(domain)
            api = _clean_api(api)
            if not domain or not api:
                await send_message(query.message, '<blockquote>❌ Invalid domain or API URL.</blockquote>')
            else:
                target = _global() if scope == 'g' else _personal(user_id)
                target = [x for x in target if x['domain'] != domain]
                target.append({'domain': domain, 'api': api})
                if scope == 'g':
                    _set_global(target)
                    await database.update_user_data(Config.OWNER_ID)
                else:
                    _set_personal(user_id, target)
                    await database.update_user_data(user_id)
                await send_message(query.message, f'<b>✅ API saved:</b> <code>{escape(domain)}</code>')
    except Exception:
        if not future.done():
            future.cancel()
    finally:
        client.remove_handler(*h)
        text, menu = _menu(user_id, _is_auth(user_id))
        await edit_message(query.message, text, menu)


@new_task
async def dlapi_command(client, message):
    if not message.chat or message.chat.type != ChatType.PRIVATE:
        await send_message(message, '<blockquote><code>/dlapi</code> works only in Bot DM.</blockquote>')
        return
    uid = message.from_user.id
    text, buttons = _menu(uid, _is_auth(uid) and (message.text or '').split()[0].lower().startswith('/dapi'))
    await send_message(message, text, buttons)


@new_task
async def dlapi_callback(client, query):
    uid = query.from_user.id
    data = query.data.split()
    if len(data) < 2:
        return
    action = data[1]
    auth = _is_auth(uid)
    if action == 'close':
        await query.answer()
        await delete_message(query.message)
        return
    if action == 'refresh':
        await query.answer('Refreshed')
        text, buttons = _menu(uid, auth)
        await edit_message(query.message, text, buttons)
        return
    if action == 'cancel':
        await query.answer('Cancelled')
        text, buttons = _menu(uid, auth)
        await edit_message(query.message, text, buttons)
        return
    if action == 'add':
        scope = data[2] if len(data) > 2 else 'p'
        if scope == 'g' and not auth:
            return await query.answer('Global configuration is restricted to Owner/Sudo.', show_alert=True)
        await _input_api(client, query, scope)
        return
    if action == 'del' and len(data) >= 4:
        scope, idx = data[2], int(data[3])
        if scope == 'g':
            if not auth:
                return await query.answer('Not allowed.', show_alert=True)
            items = _global()
            if 0 <= idx < len(items):
                items.pop(idx)
                _set_global(items)
                await database.update_user_data(Config.OWNER_ID)
        else:
            items = _personal(uid)
            if 0 <= idx < len(items):
                items.pop(idx)
                _set_personal(uid, items)
                await database.update_user_data(uid)
        await query.answer('Configuration deleted.')
        text, buttons = _menu(uid, auth)
        await edit_message(query.message, text, buttons)
