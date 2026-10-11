from time import time

from pyrogram.filters import create
from pyrogram.enums import ChatType

from ... import auth_chats, sudo_users, user_data, premium_users
from ...core.config_manager import Config
from .tg_utils import chat_info


def _source_message(update):
    return getattr(update, "message", None) or update


def _user_id(update):
    """Return a normalized sender ID, or None for anonymous/channel updates."""
    user = getattr(update, "from_user", None) or getattr(update, "sender_chat", None)
    raw_id = getattr(user, "id", None)
    try:
        return int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        return None


def _is_owner(uid):
    try:
        return uid is not None and int(uid) == int(Config.OWNER_ID)
    except (TypeError, ValueError):
        return False


def _id_in(values, uid):
    if uid is None:
        return False
    try:
        return int(uid) in {int(value) for value in values}
    except (TypeError, ValueError):
        return str(uid) in {str(value).strip() for value in values}


def _chat_context(update):
    message = _source_message(update)
    chat = getattr(message, "chat", None)
    if chat is None:
        return None, None
    thread_id = (
        message.message_thread_id
        if getattr(message, "is_topic_message", False)
        else None
    )
    return chat.id, thread_id


class CustomFilters:
    async def owner_filter(self, _, update):
        return _is_owner(_user_id(update))

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        uid = _user_id(update)
        chat_id, thread_id = _chat_context(update)
        if uid is None:
            return False
        premium_expiry = premium_users.get(uid)
        if premium_expiry:
            if premium_expiry > time():
                return True
            premium_users.pop(uid, None)
        return bool(
            _is_owner(uid)
            or (
                uid in user_data
                and (
                    user_data[uid].get("AUTH", False)
                    or user_data[uid].get("SUDO", False)
                )
            )
            or (
                chat_id in user_data
                and user_data[chat_id].get("AUTH", False)
                and (
                    thread_id is None
                    or thread_id in user_data[chat_id].get("thread_ids", [])
                )
            )
            or _id_in(sudo_users, uid)
            or _id_in(auth_chats, uid)
            or _id_in(auth_chats, chat_id)
            and (
                auth_chats[chat_id]
                and thread_id
                and thread_id in auth_chats[chat_id]
                or not auth_chats[chat_id]
            )
        )

    authorized = create(authorized_user)

    async def authorized_usetting(self, _, update):
        chat = getattr(_source_message(update), "chat", None)
        if chat and chat.type == ChatType.PRIVATE:
            return True
        uid = _user_id(update)
        if uid is None:
            return False
        is_exists = False
        if await CustomFilters.authorized("", update):
            is_exists = True
        elif chat:
            for channel_id in user_data:
                if not (
                    user_data[channel_id].get("is_auth")
                    and str(channel_id).startswith("-100")
                ):
                    continue
                try:
                    if await (await chat_info(str(channel_id))).get_member(uid):
                        is_exists = True
                        break
                except Exception:
                    continue
        return is_exists

    authorized_uset = create(authorized_usetting)

    async def sudo_user(self, _, update):
        uid = _user_id(update)
        if uid is None:
            return False
        return bool(
            _is_owner(uid)
            or (uid in user_data and user_data[uid].get("SUDO"))
            or _id_in(sudo_users, uid)
        )

    sudo = create(sudo_user)

    async def blacklisted_user(self, _, update):
        uid = _user_id(update)
        if uid is None or uid not in user_data:
            return False
        bl = user_data[uid].get("BLACKLIST", False)
        if not bl:
            return False
        if bl is True:
            return True
        if isinstance(bl, (int, float)):
            if bl > time():
                return True
            user_data[uid]["BLACKLIST"] = False
            return False
        return False

    blacklisted = create(blacklisted_user)
