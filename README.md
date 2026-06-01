# Python Mumble Bot

A voice-clip bot with two independent stacks that share a common core
(`pmb_core` — the MongoDB layer and the ffmpeg speed/pitch engine):

- **Mumble** (`mumble_bot/`) — plays clips into a Mumble channel via text commands.
- **Discord** (`discord_bot/`) — plays clips into a Discord voice channel via
  slash commands.

Each stack has its own database instance, audio directory, and web UI, so the
two clip libraries are completely separate.

Set environment variables using `deploy/.env.example` as a guide, then run the
commands below from the `deploy/` directory.

## Mumble stack

```sh
docker compose up -d
```

Web UI is exposed on host port `8001`; MongoDB on `27017`.

## Discord stack

The Discord stack runs as a separate compose project (`pmb-discord`) with its
own MongoDB instance, audio volume, and web UI. The clip library starts empty —
users upload clips through the web UI.

### One-time Discord setup

1. Create an application + bot at <https://discord.com/developers/applications>
   and copy the **bot token** into `DISCORD_BOT_TOKEN`. No privileged intents
   are required (the bot uses slash commands + voice).
2. Invite the bot to your server with an OAuth2 URL granting the
   `applications.commands` scope and the **Connect** + **Speak** voice
   permissions.
3. Put your server (guild) ID in `DISCORD_GUILD_ID` for instant slash-command
   sync. Optionally set `DISCORD_ANNOUNCE_CHANNEL_ID` to have web-triggered
   plays announced in a text channel.
4. Generate a Tailscale auth key (`DISCORD_TAILSCALE_AUTHKEY`) and a JWT secret
   (`DISCORD_JWT_SECRET_KEY`) for the Discord web UI.

### Run it

```sh
docker compose -f docker-compose.discord.yaml up -d
```

Web UI is exposed on host port `8002`; MongoDB on `27018`. Audio is stored in
`/tank/pmb/discord-audio`.

### Seed the admin user

The Discord web DB starts with no users. `winneh` is the only admin across both
stacks — seed it once after the stack is up:

```sh
docker exec disc_web python3 -c "from app.services.users import UsersService; UsersService().create_user('winneh', 'CHANGE_ME', is_admin=True); print('admin created')"
```

Additional (non-admin) users can then be registered from the web UI by the
admin.

### Slash commands

- `/play clip [speed] [pitch]` — play a clip in your voice channel (auto-joins).
  e.g. `/play clip:oy17 speed:2x pitch:3s`
- `/list [tag]` — list available clips.
- `/random count` — play random clips.
- `/volume level` — set playback volume (0–5).
