"""Per-user download API mappings and API link resolver commands."""
import json
from copy import copy
from html import escape
from urllib.parse import quote, urlparse

from niquests import AsyncSession
from pyrogram.enums import ChatType
from pyrogram.filters import command, private
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .. import bot_loop, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import send_message
from .mirror_leech import Mirror

_STORE_KEY = "DLAPI"
_PENDING = {}
_GLOBAL_KEY = "DLAPI_GLOBAL"
_LINK_KEYS = (
    "cloud_resume", "download", "download_url", "direct_link", "direct",
    "url", "link", "file_url", "src", "source", "result",
)


def _api_map(user_id):
    data = user_data.setdefault(user_id, {})
    mapping = data.get(_STORE_KEY, {})
    if not isinstance(mapping, dict):
        mapping = {}
        data[_STORE_KEY] = mapping
    return mapping


def _domain(value):
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    return value.removeprefix("www.").split(":", 1)[0].strip("./")


def _extract_links(value):
    found = []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("https://", "http://")):
            found.append(text)
        else:
            try:
                found.extend(_extract_links(json.loads(text)))
            except (ValueError, TypeError):
                pass
    elif isinstance(value, dict):
        # Prefer fields that conventionally contain actual download URLs.
        for key in _LINK_KEYS:
            if key in value:
                found.extend(_extract_links(value[key]))
        for key, item in value.items():
            if key not in _LINK_KEYS:
                found.extend(_extract_links(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_extract_links(item))
    return list(dict.fromkeys(found))


def _is_admin(uid):
    try:
        sudo = {int(x.strip()) for x in str(Config.SUDO_USERS).split() if x.strip().isdigit()}
    except Exception:
        sudo = set()
    return uid == Config.OWNER_ID or uid in sudo


def _global_map():
    return user_data.setdefault(Config.OWNER_ID, {}).setdefault(_GLOBAL_KEY, {})


def _manager_keyboard(uid):
    rows = [[InlineKeyboardButton("➕ Add API", callback_data=f"dlapi:add:{uid}")],
            [InlineKeyboardButton("📋 List APIs", callback_data=f"dlapi:list:{uid}")]]
    if _is_admin(uid):
        rows.append([InlineKeyboardButton("🌐 Global API settings", callback_data=f"dlapi:global:{uid}")])
    return InlineKeyboardMarkup(rows)


async def resolve_api_url(uid, url):
    """Resolve one matching URL through a personal or enabled global API; return URL list or None."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = _domain(parsed.netloc)
    personal = _api_map(uid).get(domain)
    global_entry = _global_map().get(domain)
    template = personal
    if isinstance(global_entry, dict):
        if global_entry.get("global"):
            template = global_entry.get("template")
        elif not template and uid == Config.OWNER_ID:
            template = global_entry.get("template")
    elif isinstance(global_entry, str) and not template:
        template = global_entry
    if not template:
        return None
    encoded = quote(url, safe="")
    api_url = template.replace("{url}", encoded) if "{url}" in template else f"{template}{encoded}"
    async with AsyncSession(timeout=180) as session:
        response = await session.get(api_url, allow_redirects=True)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception:
            payload = response.text
    return _extract_links(payload)


@new_task
async def dlapi_callback(_, query):
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        return await query.answer("Invalid action", show_alert=True)
    action, target = parts[1], int(parts[2])
    if query.from_user.id != target and not _is_admin(query.from_user.id):
        return await query.answer("This menu belongs to another user.", show_alert=True)
    if action == "add":
        _PENDING[query.from_user.id] = {"target": target, "global": False}
        await query.message.reply_text("Send API mapping as <code>domain.com=https://api.example/api?url=</code>.\nFor example: <code>gdflix.dev=https://api.example/api?url=</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"dlapi:cancel:{target}")]]))
    elif action == "global":
        _PENDING[query.from_user.id] = {"target": Config.OWNER_ID, "global": True}
        await query.message.reply_text("Send a global mapping as <code>domain.com=https://api.example/api?url=</code>. It will apply to all users once enabled.\nUse <code>/dlapi global domain.com=on</code> or <code>/dlapi global domain.com=off</code> to toggle.")
    elif action == "list":
        mapping = _api_map(target)
        global_mapping = _global_map() if _is_admin(query.from_user.id) else {}
        lines = ["<b>Download API mappings</b>"]
        rows = []
        for domain, template in mapping.items():
            lines.append(f"• <code>{escape(domain)}</code> → <code>{escape(str(template))}</code> (personal)")
            rows.append([InlineKeyboardButton(f"🗑 Delete {domain[:24]}", callback_data=f"dlapi:delete:{target}:{domain}")])
        for domain, entry in global_mapping.items():
            template = entry.get("template", "") if isinstance(entry, dict) else entry
            enabled = isinstance(entry, dict) and entry.get("global")
            lines.append(f"• <code>{escape(domain)}</code> → <code>{escape(str(template))}</code> (global {'ON' if enabled else 'OFF'})")
            rows.append([InlineKeyboardButton(f"🌐 {domain[:20]}: {'Turn OFF' if enabled else 'Turn ON'}", callback_data=f"dlapi:toggle:{target}:{domain}")])
            rows.append([InlineKeyboardButton(f"🗑 Delete global {domain[:18]}", callback_data=f"dlapi:deleteglobal:{target}:{domain}")])
        rows.extend(_manager_keyboard(target).inline_keyboard)
        await query.message.reply_text("\n".join(lines) if len(lines)>1 else "No APIs configured.", reply_markup=InlineKeyboardMarkup(rows))
    elif action in ("delete", "toggle", "deleteglobal"):
        if len(parts) < 4:
            return await query.answer("Invalid API action", show_alert=True)
        domain = _domain(":".join(parts[3:]))
        if action == "delete":
            _api_map(target).pop(domain, None)
            await database.update_user_data(target)
            await query.answer(f"Removed {domain}")
        else:
            if not _is_admin(query.from_user.id):
                return await query.answer("Only owner/sudo can manage global APIs.", show_alert=True)
            gm = _global_map()
            if action == "deleteglobal":
                gm.pop(domain, None)
                await database.update_user_data(Config.OWNER_ID)
                await query.answer(f"Removed global {domain}")
            else:
                entry = gm.get(domain)
                if not entry:
                    return await query.answer("Global API not found", show_alert=True)
                if isinstance(entry, str):
                    entry = {"template": entry, "global": False}
                entry["global"] = not bool(entry.get("global"))
                gm[domain] = entry
                await database.update_user_data(Config.OWNER_ID)
                await query.answer(f"Global API {'enabled' if entry['global'] else 'disabled'}")
        # Refresh the list after the action.
        mapping = _api_map(target)
        gm = _global_map() if _is_admin(query.from_user.id) else {}
        lines = ["<b>Download API mappings</b>"]
        lines += [f"• <code>{escape(d)}</code> → <code>{escape(str(t))}</code> (personal)" for d, t in mapping.items()]
        lines += [f"• <code>{escape(d)}</code> → <code>{escape(str(t.get('template', t)))}</code> (global {'ON' if isinstance(t, dict) and t.get('global') else 'OFF'})" for d, t in gm.items()]
        await query.message.reply_text("\n".join(lines) if len(lines) > 1 else "No APIs configured.", reply_markup=_manager_keyboard(target))
        return
    elif action == "cancel":
        _PENDING.pop(query.from_user.id, None)
        await query.message.reply_text("API setup cancelled.")
    await query.answer()


@new_task
async def dlapi_input(_, message):
    uid = message.from_user.id if message.from_user else 0
    pending = _PENDING.get(uid)
    if not pending or not message.text:
        return
    value = message.text.strip()
    target = pending["target"]
    is_global = pending.get("global", False)
    if value.lower().startswith("/dlapi "):
        return
    if "=" not in value:
        return await send_message(message, "Invalid format. Send <code>domain.com=https://api.example/api?url=</code>.")
    domain_raw, template = value.split("=", 1)
    domain, template = _domain(domain_raw), template.strip()
    parsed = urlparse(template)
    if not domain or parsed.scheme not in ("http", "https") or not parsed.netloc or ("{url}" not in template and not template.endswith(("=", "?", "&"))):
        return await send_message(message, "Invalid API mapping. Ensure the API URL ends in <code>url=</code> or contains <code>{url}</code>.")
    if is_global:
        _global_map()[domain] = {"template": template, "global": False}
        await database.update_user_data(Config.OWNER_ID)
        reply = f"Saved global API for <code>{escape(domain)}</code>. Global use is OFF by default; enable it with <code>/dlapi global {escape(domain)}=on</code>."
    else:
        _api_map(target)[domain] = template
        await database.update_user_data(target)
        reply = f"Saved API for <code>{escape(domain)}</code>."
    _PENDING.pop(uid, None)
    await send_message(message, reply, reply_markup=_manager_keyboard(uid))


@new_task
async def dlapi_command(_, message):
    """Add/list/remove per-user domain -> API templates. Private chats only."""
    if not message.from_user or message.chat.type != ChatType.PRIVATE:
        return await send_message(message, "Please use /dlapi in the bot's private chat.")

    uid = message.from_user.id
    args = message.text.split(maxsplit=1)
    value = args[1].strip() if len(args) > 1 else ""
    mapping = _api_map(uid)

    if value.lower().startswith("global "):
        if not _is_admin(uid):
            return await send_message(message, "Only the owner or sudo users can manage global APIs.")
        setting = value[7:].strip()
        if "=" not in setting:
            return await send_message(message, "Use <code>/dlapi global domain.com=on</code> or <code>/dlapi global domain.com=off</code>.")
        domain_raw, enabled = setting.split("=", 1)
        domain = _domain(domain_raw)
        entry = _global_map().get(domain)
        if not entry:
            return await send_message(message, f"No global API configured for <code>{escape(domain)}</code>.")
        if isinstance(entry, str):
            entry = {"template": entry, "global": False}
        entry["global"] = enabled.strip().lower() in {"on", "true", "yes", "1", "enable", "enabled"}
        _global_map()[domain] = entry
        await database.update_user_data(Config.OWNER_ID)
        return await send_message(message, f"Global API for <code>{escape(domain)}</code> is now <b>{'ON' if entry['global'] else 'OFF'}</b>.")

    if not value or value.lower() in {"list", "show"}:
        if not mapping:
            return await send_message(
                message,
                "<b>Download API manager</b>\n\n"
                "Add a mapping by sending:\n"
                "<code>/dlapi domain.com=https://api.example/api?url=</code>\n\n"
                "Use <code>/dlapi remove domain.com</code> to remove one.\n"
                "Use <code>/dapi https://domain.com/file/123</code> to resolve a link.", reply_markup=_manager_keyboard(uid),
            )
        lines = ["<b>Your download API mappings</b>"]
        for domain, template in sorted(mapping.items()):
            lines.append(f"• <code>{escape(domain)}</code> → <code>{escape(template)}</code>")
        lines.append("\nAdd: <code>/dlapi domain.com=https://api.example/api?url=</code>")
        lines.append("Remove: <code>/dlapi remove domain.com</code>")
        return await send_message(message, "\n".join(lines))

    if value.lower().startswith("remove "):
        domain = _domain(value[7:])
        if not domain or domain not in mapping:
            return await send_message(message, f"No API mapping found for <code>{escape(domain or value[7:])}</code>.")
        mapping.pop(domain, None)
        await database.update_user_data(uid)
        return await send_message(message, f"Removed API mapping for <code>{escape(domain)}</code>.")

    if "=" not in value:
        return await send_message(
            message,
            "Invalid format. Use:\n<code>/dlapi domain.com=https://api.example/api?url=</code>",
        )

    domain_raw, template = value.split("=", 1)
    domain = _domain(domain_raw)
    template = template.strip()
    parsed = urlparse(template)
    if not domain or not parsed.scheme in ("http", "https") or not parsed.netloc:
        return await send_message(message, "Invalid domain or API URL. Use a valid HTTPS API template.")
    if "{url}" not in template and not template.endswith(("=", "?", "&")):
        return await send_message(
            message,
            "API template must end with <code>?url=</code> or include <code>{url}</code>.",
        )
    mapping[domain] = template
    await database.update_user_data(uid)
    return await send_message(message, f"Saved API for <code>{escape(domain)}</code>.\nUse <code>/dapi https://{escape(domain)}/your-link</code> to resolve links.")


@new_task
async def dapi_command(_, message):
    """Resolve a URL through the user's configured API and return direct URLs."""
    if not message.from_user or message.chat.type != ChatType.PRIVATE:
        return await send_message(message, "Please use /dapi in the bot's private chat.")
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await send_message(
            message,
            "Usage: <code>/dapi https://domain.com/file/123 [-tm|-tc|-sync|-tch]</code>\n"
            "• <code>-tm</code>: select/reorder audio and subtitle tracks\n"
            "• <code>-tc</code>: edit audio/subtitle track title and language\n"
            "• <code>-sync</code>: open the track sync planner before upload\n"
            "• <code>-tch</code>: convert audio to AAC 7.1 where supported\n\n"
            "Manage APIs with the buttons below.", reply_markup=_manager_keyboard(message.from_user.id),
        )

    raw_args = args[1].strip().split()
    original = raw_args[0]
    task_flags = [flag for flag in raw_args[1:] if flag in ("-tm", "-tc", "-sync", "-tch")]
    parsed = urlparse(original if "://" in original else f"https://{original}")
    domain = _domain(parsed.netloc)
    mapping = _api_map(message.from_user.id)
    template = mapping.get(domain)
    if not template:
        return await send_message(
            message,
            f"No API configured for <code>{escape(domain)}</code>.\n"
            f"Add one with <code>/dlapi {escape(domain)}=https://api.example/api?url=</code>.",
        )

    encoded = quote(original, safe="")
    api_url = template.replace("{url}", encoded) if "{url}" in template else f"{template}{encoded}"
    status = await send_message(message, "Resolving link through your configured API…")
    try:
        async with AsyncSession(timeout=180) as session:
            response = await session.get(api_url, allow_redirects=True)
            response.raise_for_status()
            try:
                payload = response.json()
            except Exception:
                payload = response.text
        links = _extract_links(payload)
        if not links:
            preview = escape(json.dumps(payload, ensure_ascii=False)[:2500] if not isinstance(payload, str) else payload[:2500])
            return await status.edit_text(f"API returned no download URL.\n<pre>{preview}</pre>")
        # Feed the first extracted direct URL into the normal Mirror pipeline so
        # download, post-processing, and configured upload destinations run as usual.
        # Work on a shallow message copy: never mutate the user's original /dapi text.
        task_message = copy(message)
        task_message.text = f"/mirror {links[0]}" + (f" {' '.join(task_flags)}" if task_flags else "")
        await status.edit_text(
            "<b>Direct link extracted successfully.</b>\n"
            "Starting the normal download → process → upload pipeline…\n\n"
            f"<code>{escape(links[0])}</code>",
            disable_web_page_preview=True,
        )
        bot_loop.create_task(Mirror(TgClient.bot, task_message).new_event())
        if len(links) > 1:
            await send_message(
                message,
                f"API returned {len(links)} links; started the first extracted download link. "
                "Use the API response structure to configure one direct download URL per request.",
            )
    except Exception as exc:
        await status.edit_text(f"API request failed: <code>{escape(str(exc)[:800])}</code>")


def register_dapi_handlers():
    TgClient.bot.add_handler(MessageHandler(dlapi_input, filters=private & ~command(BotCommands.DlapiCommand, case_sensitive=True)), group=9)
    TgClient.bot.add_handler(CallbackQueryHandler(dlapi_callback, filters=__import__("pyrogram").filters.regex(r"^dlapi:")), group=9)
    TgClient.bot.add_handler(
        MessageHandler(dlapi_command, filters=command(BotCommands.DlapiCommand, case_sensitive=True) & private)
    )
    TgClient.bot.add_handler(
        MessageHandler(dapi_command, filters=command(BotCommands.DapiCommand, case_sensitive=True) & private)
    )
