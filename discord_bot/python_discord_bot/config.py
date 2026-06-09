import os


def _int_env(name):
    value = os.getenv(name)
    return int(value) if value else None


# Discord bot token (required).
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# If set, slash commands are synced to this single guild (instant). Otherwise
# they are synced globally (can take up to an hour to appear).
GUILD_ID = _int_env("DISCORD_GUILD_ID")

# If set, web-triggered plays ("X played: ...") are announced in this text
# channel. If unset, no announcements are posted.
ANNOUNCE_CHANNEL_ID = _int_env("DISCORD_ANNOUNCE_CHANNEL_ID")

# "Clip that" instant replay: when on, the bot connects to voice with receive
# enabled and keeps a rolling per-user buffer (opted-in users only) that the web
# can turn into a clip. Off by default — receiving means decoding everyone's
# audio, so it's only worth enabling where the feature is wanted.
CLIP_CAPTURE_ENABLED = os.getenv("CLIP_CAPTURE_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)
