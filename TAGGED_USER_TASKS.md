# Tagged user tasks — implementation specification

The intended syntax is to put a target user on the final line of an otherwise normal mirror/leech command:

```text
/mirror https://example.com/file.mkv
@target_username
```

or

```text
/leech https://example.com/file.mkv
123456789
```

Expected behavior:
- Only an existing Telegram user may be targeted. Resolve usernames through Telegram; do not guess a user ID from a username.
- If the target does not exist or cannot be resolved, reply `User not existed. Task not started.` and do not enqueue or start any download.
- The command source must already be authorized: bot owner, configured authorized user, sudo user, or an authorized chat/channel post. A tag must never grant permissions by itself.
- For a group linked to a channel, channel-originated posts must be checked against the configured/authorized source chat and the channel's linked-chat relationship; do not accept arbitrary messages from unrelated chats.
- When accepted, the task must use the target user's saved `user_data` settings (destination, naming, metadata, thumbnails, split/merge preferences, etc.) and charge limits/task counts to that target user. Keep the original source message/chat for audit/logging.
- Resolve the target before task construction, access checks, quota checks, queue insertion, or downloader startup. Fail closed if identity or permissions cannot be verified.

This file documents the required behavior; it is not a claim that tagged-task routing has already been wired into all command handlers. The current HTR-X command flow constructs `Mirror` directly from the source message, while WZML-X's `CustomFilters.authorized` and `TaskConfig` illustrate the existing authorization and per-user-settings patterns. Correct implementation requires a coordinated change to command handlers, task identity/settings initialization, permission checks, and logging—not just a README change.
