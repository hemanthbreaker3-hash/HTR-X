from asyncio import Event, wait_for
from html import escape
from urllib.parse import urlparse
import json
import re

from niquests import AsyncSession
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.filters import private, user
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from .. import LOGGER, user_data
from ..core.config_manager import Config
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import delete_message, send_message
from ..helper.ext_utils.bot_utils import new_task


def _sudo_ids():
    ids = getattr(Config, "SUDO_USERS", [])
    if isinstance(ids, str):
        ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    return set(ids or [])


def _is_auth(user_id):
    return user_id == Config.OWNER_ID or user_id in _sudo_ids() or bool(
        user_data.get(user_id, {}).get("SUDO")
        or user_data.get(user_id, {}).get("AUTH")
    )


def _normalize_domain(value):
    value = value.strip().lower().rstrip("/")
    if "://" in value:
        value = urlparse(value).hostname or ""
    value = value.split("/", 1)[0].split(":", 1)[0].strip(".")
    if value.startswith("www."):
        value = value[4:]
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", value):
        return ""
    return value


def _normalize_api(value):
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        return ""
    if "url=" not in value and "{url}" not in value:
        return ""
    return value


def _parse_mapping(text):
    if "=" not in text:
        return None, "Use exactly: <code>gdflix.com=https://example.com/api?url=</code>"
    domain, api = text.split("=", 1)
    domain = _normalize_domain(domain)
    api = _normalize_api(api)
    if not domain:
        return None, "Invalid domain."
    if not api:
        return None, "API must be an HTTP(S) URL containing <code>url=</code> or <code>{url}</code>."
    return (domain, api), None


async def _get_global():
    try:
        return await database.get_dlapi_global()
    except Exception as e:
        LOGGER.warning(f"DL API global config read failed: {e}")
        return {}


async def _get_user_configs(user_id):
    return dict(user_data.get(user_id, {}).get("DLAPI") or {})


async def _save_user_configs(user_id, configs):
    user_data.setdefault(user_id, {})["DLAPI"] = dict(configs)
    await database.update_user_data(user_id)


async def _save_global(configs):
    await database.set_dlapi_global(configs)


def _matching_config(link, configs):
    try:
        host = (urlparse(link).hostname or "").lower().rstrip(".")
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    # Longest domain wins, so e.g. sub.example.com can override example.com.
    matches = [
        (domain, api)
        for domain, api in (configs or {}).items()
        if host == domain or host.endswith("." + domain)
    ]
    return max(matches, key=lambda x: len(x[0]))[1] if matches else None


def _build_api(api, link):
    if "{url}" in api:
        return api.replace("{url}", link)
    # The requested format intentionally keeps the nested URL unescaped:
    # https://.../api/gdflix?url=https://gdflix.dev/file/...
    before, after = api.split("url=", 1)
    if after and not after.startswith(("&", "#")):
        # Preserve any query suffix after the template value.
        suffix = ""
        if "&" in after:
            suffix = "&" + after.split("&", 1)[1]
        return f"{before}url={link}{suffix}"
    return f"{api}{link}"


def _extract_http_urls(value, source_link=""):
    """Return HTTP(S) URLs from arbitrary JSON values, preserving URL text."""
    found = []
    seen = set()

    def add(candidate):
        if not isinstance(candidate, str):
            return
        candidate = candidate.strip().strip("\"'")
        if not candidate.startswith(("https://", "http://")):
            return
        if candidate == source_link or candidate in seen:
            return
        # Ignore obvious JSON/document URLs; keep CDN links and URLs containing
        # spaces (valid in some generated filenames) untouched.
        if candidate.lower().endswith((".json", ".json/")):
            return
        seen.add(candidate)
        found.append(candidate)

    def walk(obj):
        if isinstance(obj, dict):
            # Prefer values of common download-related keys, then inspect every
            # other value. Nothing except an actual HTTP(S) URL is returned.
            preferred = (
                "download", "download_url", "downloadUrl", "direct",
                "direct_url", "directUrl", "url", "link", "href",
                "cloud_resume", "resume", "file", "src",
            )
            done = set()
            for key in preferred:
                if key in obj:
                    done.add(key)
                    walk(obj[key])
            for key, item in obj.items():
                if key not in done:
                    walk(item)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            text = obj.strip()
            # A JSON string can itself be a complete URL, including spaces in
            # a generated filename. Keep that complete value.
            if text.startswith(("https://", "http://")):
                add(text)
                return
            # For text such as "Download: https://..." only extract the actual
            # URL and ignore the surrounding text.
            for match in re.finditer(r"https?://[^\"'<>\r\n]+", text):
                candidate = match.group(0).rstrip(".,;)]}\"'")
                add(candidate)

    walk(value)
    return found


def _find_download_urls(obj, source_link=""):
    return _extract_http_urls(obj, source_link)


async def _probe_download_url(session, url):
    """Check a candidate without downloading the complete file."""
    try:
        response = await session.head(url, allow_redirects=True, timeout=20)
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        if 200 <= status < 400 and "text/html" not in content_type:
            return True
    except Exception:
        pass

    try:
        response = await session.get(
            url,
            headers={"Range": "bytes=0-0"},
            allow_redirects=True,
            timeout=20,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        return 200 <= status < 400 and "text/html" not in content_type
    except Exception:
        return False


async def resolve_custom_dlapi(link, user_id):
    if not isinstance(link, str) or not link.startswith(("http://", "https://")):
        return None
    user_cfg = _get_user_configs(user_id)
    global_cfg = await _get_global()
    api = _matching_config(link, user_cfg)
    if not api:
        api = _matching_config(link, global_cfg)
    if not api:
        return None

    api_url = _build_api(api, link)
    candidates = []
    try:
        # Some APIs take time to generate a CDN link, so allow a full 120s.
        async with AsyncSession(
            timeout=120,
            headers={
                "User-Agent": "Mozilla/5.0 HTR-X-DLAPI",
                "Accept": "application/json,text/plain,*/*",
            },
        ) as session:
            response = await session.get(api_url, allow_redirects=True, timeout=120)
            response.raise_for_status()
            try:
                payload = response.json()
            except Exception:
                try:
                    payload = json.loads(response.text)
                except Exception:
                    payload = response.text

            candidates = _find_download_urls(payload, link)
            if not candidates:
                raise ValueError("API output did not contain an HTTP(S) download URL.")

            # Preserve API order. The first usable URL wins; if it is dead,
            # try the next URL returned by the API.
            for candidate in candidates:
                if await _probe_download_url(session, candidate):
                    return candidate

        raise ValueError(
            f"API returned {len(candidates)} HTTP(S) link(s), but none are reachable."
        )
    except Exception as e:
        LOGGER.warning(f"Custom DL API failed for {link}: {e}")
        raise RuntimeError(f"DL API failed: {e}") from e


def _render_configs(title, configs):
    if not configs:
        return f"{title}\n\n<blockquote>No API configurations added yet.</blockquote>"
    lines = [title, ""]
    for domain, api in sorted(configs.items()):
        lines.append(f"• <code>{escape(domain)}</code> → <code>{escape(api)}</code>")
    return "\n".join(lines)


async def _wait_for_mapping(client, user_id, prompt):
    await send_message(prompt, "Send the API mapping in this format:\n<code>gdflix.com=https://ddl-y1lj.onrender.com/api/gdflix?url=</code>\n\n<i>Waiting 120 seconds...</i>")
    event = Event()
    result = {}

    async def capture(_, msg):
        if msg.from_user and msg.from_user.id == user_id and msg.chat.type == ChatType.PRIVATE:
            if not (msg.text or "").startswith("/"):
                result["message"] = msg
                event.set()

    handler = client.add_handler(
        MessageHandler(capture, filters=private & user(user_id)),
        group=-2,
    )
    try:
        try:
            await wait_for(event.wait(), timeout=120)
        except Exception:
            return None, "Timed out."
        msg = result.get("message")
        return _parse_mapping(msg.text or "")
    finally:
        client.remove_handler(*handler)


def _main_menu(user_id, auth, user_cfg, global_cfg):
    buttons = ButtonMaker()
    buttons.data_button("➕ Add API", "dlapi add")
    buttons.data_button("🔎 Resolve Link", "dlapi resolve")
    if auth:
        buttons.data_button("➕ Add Global", "dapi global", position="header")
        buttons.data_button("➕ Add Alone", "dapi alone", position="header")
    buttons.data_button("✖️ Close", "dlapi close", position="footer", style=ButtonStyle.DANGER)
    text = "<b>🔗 Direct Link API Manager</b>\n\n"
    text += "<blockquote>DM only. Add unlimited domain → API mappings. Matching links are resolved through the configured API and the first HTTP(S) download URL in its JSON response is used.</blockquote>\n\n"
    text += _render_configs("<b>👤 Your APIs</b>", user_cfg)
    if auth:
        text += "\n\n" + _render_configs("<b>🌐 Global APIs</b>", global_cfg)
        text += "\n\n<i>Global APIs apply to every user. Alone APIs apply only to the configured auth user.</i>"
    return text, buttons.build_menu(2)


@new_task
async def dlapi_command(client, message):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(message, "<blockquote><code>/dlapi</code> works only in bot DM.</blockquote>")
        return
    uid = message.from_user.id
    user_cfg = _get_user_configs(uid)
    global_cfg = await _get_global()
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1:
        link = args[1].strip()
        await _resolve_and_reply(message, uid, link)
        return
    text, buttons = _main_menu(uid, _is_auth(uid), user_cfg, global_cfg)
    await send_message(message, text, buttons)


async def _resolve_and_reply(message, uid, link):
    if not link.startswith(("http://", "https://")):
        await send_message(message, "<blockquote>Send a valid HTTP(S) link.</blockquote>")
        return
    user_cfg = _get_user_configs(uid)
    global_cfg = await _get_global()
    api = _matching_config(link, user_cfg) or _matching_config(link, global_cfg)
    if not api:
        await send_message(message, f"<blockquote>No DL API configured for <code>{escape(urlparse(link).hostname or '')}</code>.</blockquote>")
        return
    status = await send_message(message, "<b>🔗 Resolving through configured DL API...</b>")
    try:
        result = await resolve_custom_dlapi(link, uid)
        await status.edit_text(
            f"<b>✅ Direct Download Link</b>\n\n<code>{escape(result)}</code>",
            reply_markup=ButtonMaker().build_menu(1) if False else None,
        )
        buttons = ButtonMaker()
        buttons.url_button("⬇️ Download", result)
        await status.edit_reply_markup(buttons.build_menu(1))
    except Exception as e:
        await status.edit_text(f"<blockquote>❌ {escape(str(e))}</blockquote>")


async def dlapi_callback(client, query):
    uid = query.from_user.id
    if query.message.chat.type != ChatType.PRIVATE:
        await query.answer("DM only.", show_alert=True)
        return
    data = (query.data or "").split()
    action = data[1] if len(data) > 1 else ""
    if action == "close":
        await query.answer()
        await delete_message(query.message)
        return
    if action == "resolve":
        await query.answer()
        await send_message(query.message, "Send the source URL to resolve (for example a GDFlix link).")
        # The next non-command DM is intentionally handled by a short-lived
        # private handler, so the command does not need a permanent state table.
        event = Event()
        result = {}

        async def capture(_, msg):
            if msg.from_user and msg.from_user.id == uid and msg.chat.type == ChatType.PRIVATE:
                if msg.text and not msg.text.startswith("/"):
                    result["message"] = msg
                    event.set()

        handler = client.add_handler(
            MessageHandler(capture, filters=private & user(uid)),
            group=-2,
        )
        try:
            try:
                await wait_for(event.wait(), timeout=120)
            except Exception:
                await send_message(query.message, "<blockquote>Timed out.</blockquote>")
                return
            link = (result["message"].text or "").split()[0]
            await _resolve_and_reply(query.message, uid, link)
        finally:
            client.remove_handler(*handler)
        return
    if action == "add":
        await query.answer()
        mapping, error = await _wait_for_mapping(client, uid, query.message)
        if error:
            await send_message(query.message, f"<blockquote>❌ {error}</blockquote>")
            return
        domain, api = mapping
        cfg = _get_user_configs(uid)
        cfg[domain] = api
        await _save_user_configs(uid, cfg)
        text, buttons = _main_menu(uid, _is_auth(uid), cfg, await _get_global())
        await query.message.edit_text(text, reply_markup=buttons)
        return
    await query.answer("Unknown action.", show_alert=True)


async def dapi_callback(client, query):
    uid = query.from_user.id
    if not _is_auth(uid):
        await query.answer("Owner/Sudo only.", show_alert=True)
        return
    if query.message.chat.type != ChatType.PRIVATE:
        await query.answer("DM only.", show_alert=True)
        return
    data = (query.data or "").split()
    scope = data[1] if len(data) > 1 else ""
    if scope not in ("global", "alone"):
        await query.answer()
        return
    await query.answer()
    if scope == "global":
        cfg = await _get_global()
        mapping, error = await _wait_for_mapping(client, uid, query.message)
        if error:
            await send_message(query.message, f"<blockquote>❌ {error}</blockquote>")
            return
        domain, api = mapping
        cfg[domain] = api
        await _save_global(cfg)
    else:
        cfg = _get_user_configs(uid)
        mapping, error = await _wait_for_mapping(client, uid, query.message)
        if error:
            await send_message(query.message, f"<blockquote>❌ {error}</blockquote>")
            return
        domain, api = mapping
        cfg[domain] = api
        await _save_user_configs(uid, cfg)
    user_cfg = _get_user_configs(uid)
    global_cfg = await _get_global()
    text, buttons = _main_menu(uid, True, user_cfg, global_cfg)
    await query.message.edit_text(text, reply_markup=buttons)


@new_task
async def dapi_command(client, message):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(message, "<blockquote><code>/dapi</code> works only in bot DM.</blockquote>")
        return
    uid = message.from_user.id
    if not _is_auth(uid):
        await send_message(message, "<blockquote><code>/dapi</code> is restricted to Owner/Sudo users.</blockquote>")
        return
    user_cfg = _get_user_configs(uid)
    global_cfg = await _get_global()
    text, buttons = _main_menu(uid, True, user_cfg, global_cfg)
    await send_message(message, text, buttons)
