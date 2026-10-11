"""Premium membership commands. Premium grants normal bot access, never sudo privileges."""
import re
from math import ceil
from time import time
from pyrogram import filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .. import premium_users, user_data, LOGGER
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.ext_utils.db_handler import database

_DURATION = re.compile(r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks|mo|month|months|y|yr|yrs|year|years)$", re.I)
_UNITS = {
    "s":1,"sec":1,"secs":1,"second":1,"seconds":1,
    "m":60,"min":60,"mins":60,"minute":60,"minutes":60,
    "h":3600,"hr":3600,"hrs":3600,"hour":3600,"hours":3600,
    "d":86400,"day":86400,"days":86400,
    "w":604800,"week":604800,"weeks":604800,
    "mo":2592000,"month":2592000,"months":2592000,
    "y":31536000,"yr":31536000,"yrs":31536000,"year":31536000,"years":31536000,
}
PAGE_SIZE = 8

def _duration(value):
    match = _DURATION.fullmatch(value.strip())
    if not match:
        raise ValueError("Invalid duration. Examples: 30s, 15m, 2h, 1d, 2months, 1y.")
    seconds = int(match.group(1)) * _UNITS[match.group(2).lower()]
    if seconds < 1 or seconds > 10 * 31536000:
        raise ValueError("Duration must be between 1 second and 10 years.")
    return seconds

def _resolve_user(value):
    value = value.strip()
    if value.startswith("@"):
        username = value[1:].lower()
        for uid, data in user_data.items():
            if str(data.get("USERNAME", data.get("username", ""))).lstrip("@").lower() == username:
                return int(uid)
        raise ValueError("Username not found in the bot's known users. Ask that user to start the bot or use their numeric ID.")
    return int(value)

async def _persist(uid, expiry):
    premium_users[uid] = expiry
    if not getattr(database, "_return", True) and database.db is not None:
        await database.db.settings.premium_users.update_one(
            {"_id": str(uid)}, {"$set": {"expiry": expiry}}, upsert=True
        )

async def _load():
    if getattr(database, "_return", True) or database.db is None:
        return
    async for doc in database.db.settings.premium_users.find({}):
        try:
            uid, expiry = int(doc["_id"]), float(doc["expiry"])
            if expiry > time():
                premium_users[uid] = expiry
            else:
                await database.db.settings.premium_users.delete_one({"_id": doc["_id"]})
        except (KeyError, TypeError, ValueError):
            continue

async def premium_add(client, message):
    uid = getattr(getattr(message, "from_user", None), "id", None)
    if not (uid == int(Config.OWNER_ID) or uid in {int(x) for x in __import__("bot").sudo_users}):
        return
    args = (message.text or "").split()
    if len(args) != 3:
        await message.reply_text("Usage: /addpremium <user_id|@username> <duration>\nExample: /addpremium 7731989008 1d")
        return
    try:
        target, seconds = _resolve_user(args[1]), _duration(args[2])
    except (ValueError, TypeError) as exc:
        await message.reply_text(f"❌ {exc}")
        return
    expiry = max(time(), premium_users.get(target, 0)) + seconds
    await _persist(target, expiry)
    await message.reply_text(f"✅ Premium enabled for <code>{target}</code>.\nExpires: <code>{__import__('datetime').datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')}</code>")

async def premium_remove(client, message):
    uid = getattr(getattr(message, "from_user", None), "id", None)
    if not (uid == int(Config.OWNER_ID) or uid in {int(x) for x in __import__("bot").sudo_users}):
        return
    args = (message.text or "").split()
    if len(args) not in (2, 3):
        await message.reply_text("Usage:\n/delpremium <user_id> — remove premium\n/delpremium <user_id> <duration> — subtract duration")
        return
    try:
        target = _resolve_user(args[1])
        if target not in premium_users:
            await _load()
        expiry = premium_users.get(target)
        if not expiry or expiry <= time():
            await message.reply_text("That user has no active premium membership.")
            return
        if len(args) == 2:
            premium_users.pop(target, None)
            if not getattr(database, "_return", True) and database.db is not None:
                await database.db.settings.premium_users.delete_one({"_id": str(target)})
            await message.reply_text(f"✅ Premium removed for <code>{target}</code>.")
            return
        remaining = expiry - _duration(args[2])
        if remaining <= time():
            premium_users.pop(target, None)
            if not getattr(database, "_return", True) and database.db is not None:
                await database.db.settings.premium_users.delete_one({"_id": str(target)})
            await message.reply_text("✅ Duration removed; premium has expired and was revoked.")
        else:
            await _persist(target, remaining)
            await message.reply_text(f"✅ Removed {args[2]} from <code>{target}</code>'s premium. Remaining: <code>{int((remaining-time())//86400)}d</code>.")
    except (ValueError, TypeError) as exc:
        await message.reply_text(f"❌ {exc}")

async def premium_list(client, message):
    uid = getattr(getattr(message, "from_user", None), "id", None)
    if not (uid == int(Config.OWNER_ID) or uid in {int(x) for x in __import__("bot").sudo_users}):
        return
    await _load()
    await _show_page(message, 0)

async def _show_page(message, page, edit=False):
    now = time()
    active = sorted([(uid, exp) for uid, exp in premium_users.items() if exp > now], key=lambda item:item[1])
    pages = max(1, ceil(len(active)/PAGE_SIZE))
    page = max(0, min(page, pages-1))
    chunk = active[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
    text = f"<b>👑 Premium Users</b>\nPage {page+1}/{pages} • Total: {len(active)}\n\n"
    if chunk:
        for uid, exp in chunk:
            left = max(0, int(exp-now))
            days, rem = divmod(left, 86400)
            hours, rem = divmod(rem, 3600)
            minutes = rem // 60
            text += f"• <code>{uid}</code> — {days}d {hours}h {minutes}m left\n"
    else:
        text += "No active premium users."
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Back", callback_data=f"premium_page:{page-1}"))
    if page < pages-1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"premium_page:{page+1}"))
    if nav: buttons.append(nav)
    markup = InlineKeyboardMarkup(buttons) if buttons else None
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)

async def premium_page_callback(client, query):
    if not await CustomFilters.sudo("", query):
        await query.answer("Sudo only.", show_alert=True)
        return
    await _load()
    page = int(query.data.split(":")[-1])
    await _show_page(query.message, page, edit=True)
    await query.answer()

async def load_premium_users():
    await _load()

def register_premium_handlers():
    suffix = Config.CMD_SUFFIX or ""
    TgClient.bot.add_handler(MessageHandler(premium_add, filters.command(f"addpremium{suffix}") & CustomFilters.sudo))
    TgClient.bot.add_handler(MessageHandler(premium_remove, filters.command(f"delpremium{suffix}") & CustomFilters.sudo))
    TgClient.bot.add_handler(MessageHandler(premium_list, filters.command(f"premium_users{suffix}") & CustomFilters.sudo))
    TgClient.bot.add_handler(CallbackQueryHandler(premium_page_callback, filters.regex(r"^premium_page:\d+$")))
