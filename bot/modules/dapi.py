"""Per-user download API mappings and API link resolver commands."""
import json
from copy import copy
from html import escape
from urllib.parse import quote, urlparse
import re

from niquests import AsyncSession
from pyrogram.enums import ChatType
from pyrogram.filters import command, private
from pyrogram.handlers import MessageHandler

from .. import bot_loop, user_data
from ..core.tg_client import TgClient
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import send_message
from .mirror_leech import Mirror

_STORE_KEY = "DLAPI"
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
    """Recursively collect HTTP(S) URLs from arbitrary JSON values/text."""
    found = []
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if parsed is not None:
            found.extend(_extract_links(parsed))
        for link in re.findall(r"https?://[^\s\"'<> \[\]{}]+", text, flags=re.I):
            link = link.rstrip(".,;:)")
            if urlparse(link).netloc:
                found.append(link)
    elif isinstance(value, dict):
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


def _global_map():
    """Global API mappings are stored with the configured owner in user_data."""
    try:
        owner_id = int(Config.OWNER_ID)
    except (TypeError, ValueError):
        owner_id = 0
    if not owner_id:
        return {}
    data = user_data.setdefault(owner_id, {})
    mapping = data.get("DLAPI_GLOBAL", {})
    if not isinstance(mapping, dict):
        mapping = {}
        data["DLAPI_GLOBAL"] = mapping
    return mapping


async def _is_admin(message):
    """Return true for the owner or users explicitly authorized in bot data."""
    user = getattr(message, "from_user", None)
    if not user:
        return False
    try:
        if user.id == int(Config.OWNER_ID):
            return True
    except (TypeError, ValueError):
        pass
    info = user_data.get(user.id, {})
    return bool(info.get("AUTH") or info.get("SUDO") or info.get("is_sudo"))


@new_task
async def dlapi_command(_, message):
    """Add/list/remove per-user domain -> API templates. Private chats only."""
    if not message.from_user or message.chat.type != ChatType.PRIVATE:
        return await send_message(message, "Please use /dlapi in the bot's private chat.")

    uid = message.from_user.id
    args = message.text.split(maxsplit=1)
    value = args[1].strip() if len(args) > 1 else ""
    mapping = _api_map(uid)
    is_admin = await _is_admin(message)
    global_mode = False
    if value.lower().startswith("global "):
        if not is_admin:
            return await send_message(message, "Only the owner or authorized users can manage global APIs.")
        global_mode = True
        value = value[7:].strip()
        mapping = _global_map()
    elif value.lower() in {"global", "global list"}:
        if not is_admin:
            return await send_message(message, "Only the owner or authorized users can view global APIs.")
        mapping = _global_map()
        global_mode = True
        value = "list"

    if not value or value.lower() in {"list", "show"}:
        if not mapping:
            return await send_message(
                message,
                "<b>Download API manager</b>\n\n"
                "Add a mapping by sending:\n"
                "<code>/dlapi domain.com=https://api.example/api?url=</code>\n\n"
                "Use <code>/dlapi remove domain.com</code> to remove one.\n"
                "Use <code>/dapi https://domain.com/file/123</code> to resolve a link.",
            )
        lines = ["<b>Global download API mappings</b>" if global_mode else "<b>Your download API mappings</b>"]
        for domain, template in sorted(mapping.items()):
            lines.append(f"• <code>{escape(domain)}</code> → <code>{escape(template)}</code>")
        lines.append("\nAdd: <code>/dlapi domain.com=https://api.example/api?url=</code>")
        if is_admin:
            lines.append("Global: <code>/dlapi global domain.com=https://api.example/api?url=</code>")
        lines.append("Remove: <code>/dlapi remove domain.com</code>")
        return await send_message(message, "\n".join(lines))

    if value.lower().startswith("remove "):
        domain = _domain(value[7:])
        if not domain or domain not in mapping:
            return await send_message(message, f"No API mapping found for <code>{escape(domain or value[7:])}</code>.")
        mapping.pop(domain, None)
        await database.update_user_data(int(Config.OWNER_ID) if global_mode else uid)
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
    await database.update_user_data(int(Config.OWNER_ID) if global_mode else uid)
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
            "• <code>-tch</code>: convert audio to AAC 7.1 where supported",
        )

    raw_args = args[1].strip().split()
    original = raw_args[0]
    task_flags = [flag for flag in raw_args[1:] if flag in ("-tm", "-tc", "-sync", "-tch")]
    parsed = urlparse(original if "://" in original else f"https://{original}")
    domain = _domain(parsed.netloc)
    mapping = _api_map(message.from_user.id)
    template = mapping.get(domain) or _global_map().get(domain)
    if not template:
        return await send_message(
            message,
            f"No API configured for <code>{escape(domain)}</code>.\n"
            f"Add one with <code>/dlapi {escape(domain)}=https://api.example/api?url=</code>.",
        )

    encoded = quote(original, safe=":/?=&%")
    api_url = template.replace("{url}", encoded) if "{url}" in template else f"{template}{encoded}"
    status = await send_message(message, "Resolving link through your configured API…")
    try:
        async with AsyncSession(timeout=30) as session:
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
    TgClient.bot.add_handler(
        MessageHandler(dlapi_command, filters=command(BotCommands.DlapiCommand, case_sensitive=True) & private)
    )
    TgClient.bot.add_handler(
        MessageHandler(dapi_command, filters=command(BotCommands.DapiCommand, case_sensitive=True) & private)
    )
