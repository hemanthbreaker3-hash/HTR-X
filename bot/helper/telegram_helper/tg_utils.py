from asyncio import gather
from time import time
from uuid import uuid4

from pyrogram.enums import ChatAction
from pyrogram.errors import ChannelInvalid, PeerIdInvalid, RPCError, UserNotParticipant

from ..ext_utils.links_utils import encode_slink

from ... import LOGGER, user_data
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.shortener_utils import short_url
from ..ext_utils.status_utils import get_readable_time
from .button_build import ButtonMaker


_FORCESUB_CACHE = {}
_FORCESUB_CACHE_TTL = 30


async def chat_info(channel_id):
    channel_id = str(channel_id).strip()
    if channel_id.startswith("-100"):
        channel_id = int(channel_id)
    elif channel_id.startswith("@"):
        channel_id = channel_id.replace("@", "")
    else:
        return None
    try:
        return await TgClient.bot.get_chat(channel_id)
    except (PeerIdInvalid, ChannelInvalid) as e:
        LOGGER.error(f"{e.NAME}: {e.MESSAGE} for {channel_id}")
        return None


async def forcesub(message, ids, button=None):
    # Force-sub must fail open when Telegram cannot resolve a configured channel.
    # A broken/old channel ID should never block every command.
    button = ButtonMaker() if button is None else button
    join_button = {}
    _msg = ""
    user = message.from_user
    if not user:
        return _msg, button

    channel_ids = []
    for raw in str(ids or "").replace(",", " ").split():
        raw = raw.strip()
        if raw and raw not in channel_ids:
            channel_ids.append(raw)

    async def _check_channel(channel_id):
        cache_key = (user.id, channel_id)
        cached = _FORCESUB_CACHE.get(cache_key)
        now = time()
        if cached and now - cached[0] < _FORCESUB_CACHE_TTL:
            return cached[1]
        chat = await chat_info(channel_id)
        if chat is None:
            LOGGER.warning(f"Force-sub skipped unresolved channel: {channel_id}")
            return None
        try:
            member = await chat.get_member(user.id)
            # Telegram can return a member object for all valid membership states.
            if getattr(member, "status", None) in ("left", "kicked"):
                raise UserNotParticipant
            _FORCESUB_CACHE[cache_key] = (now, None)
            return None
        except UserNotParticipant:
            invite_link = None
            if getattr(chat, "username", None):
                invite_link = f"https://t.me/{chat.username}"
            else:
                invite_link = getattr(chat, "invite_link", None)
                if not invite_link:
                    try:
                        invite_link = await TgClient.bot.export_chat_invite_link(chat.id)
                    except Exception as e:
                        LOGGER.warning(f"Could not create Force-sub invite for {channel_id}: {e}")
            if invite_link:
                result = (chat.title or str(chat.id), invite_link)
                _FORCESUB_CACHE[cache_key] = (now, result)
                return result
            # Membership was confirmed missing but there is no usable join URL.
            # Do not turn this into a global command outage.
            return None
        except RPCError as e:
            LOGGER.warning(f"Force-sub membership check failed for {channel_id}: {e}")
        except Exception as e:
            LOGGER.warning(f"Force-sub membership check failed for {channel_id}: {e}")
        return None

    results = await gather(*[_check_channel(cid) for cid in channel_ids])
    for result in results:
        if result:
            title, link = result
            join_button[title] = link

    if join_button:
        if button is None:
            button = ButtonMaker()
        _msg = "┠ Channel(s) pending to be joined, Join Now!"
        for key, value in join_button.items():
            button.url_button(f"Join {key}", value, "footer")
    return _msg, button


async def user_info(user_id):
    try:
        return await TgClient.bot.get_users(user_id)
    except Exception:
        return ""


async def check_botpm(message, button=None):
    button = ButtonMaker() if button is None else button
    try:
        await TgClient.bot.send_chat_action(message.from_user.id, ChatAction.TYPING)
        return None, button
    except Exception:
        _msg = "┠ <i>Bot isn't Started in PM or Inbox (Private)</i>"
        button.url_button(
            "Start Bot Now", f"https://t.me/{TgClient.BNAME}?start=start", "header"
        )
        return _msg, button


async def verify_token(user_id, button=None):
    button = ButtonMaker() if button is None else button
    if not Config.VERIFY_TIMEOUT or bool(
        user_id == Config.OWNER_ID
        or user_id in user_data
        and user_data[user_id].get("is_sudo")
    ):
        return None, button
    user_data.setdefault(user_id, {})
    data = user_data[user_id]
    expire = data.get("VERIFY_TIME")
    if Config.LOGIN_PASS and data.get("VERIFY_TOKEN", "") == Config.LOGIN_PASS:
        return None, button
    isExpired = (
        expire is None
        or expire is not None
        and (time() - expire) > Config.VERIFY_TIMEOUT
    )
    if isExpired:
        token = (
            data["VERIFY_TOKEN"]
            if expire is None and "VERIFY_TOKEN" in data
            else str(uuid4())
        )
        if expire is not None:
            del data["VERIFY_TIME"]
        data["VERIFY_TOKEN"] = token
        user_data[user_id].update(data)
        encrypt_url = encode_slink(f"{token}&&{user_id}")
        button.url_button(
            "Verify Access Token",
            await short_url(f"https://t.me/{TgClient.BNAME}?start={encrypt_url}"),
        )
        return (
            f"┠ <i>Verify Access Token has been expired,</i> Kindly validate a new access token to start using bot again.\n┃\n┖ <b>Validity :</b> <code>{get_readable_time(Config.VERIFY_TIMEOUT)}</code>",
            button,
        )
    return None, button
