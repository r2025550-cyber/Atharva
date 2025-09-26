# Telegram Advanced Music Bot (Railway + GitHub Ready)

A **voice chat music bot** for Telegram groups using **Pyrogram + PyTgCalls + FFmpeg + yt-dlp**.

## ✨ Features
- Join/leave voice chat
- Play from YouTube URL or text search
- Queue with `/queue` and live now-playing
- Controls: `/play`, `/skip`, `/pause`, `/resume`, `/stop`, `/volume 0-200`
- Admin-only controls (configurable)
- Graceful auto-reconnect
- Dockerized; works on **Railway** (long polling)

> ⚠️ Voice chat streaming requires a **user session** (assistant account). Generate `SESSION_STRING` once, then set as env var.

---

## 🔧 Environment Variables
Create `.env` locally or set in Railway Variables:

```
API_ID=123456             # from my.telegram.org
API_HASH=abcdef123456789  # from my.telegram.org
BOT_TOKEN=1234:abcd-...   # @BotFather
SESSION_STRING=...        # assistant user session (see below)
ADMINS=12345,67890        # Telegram user IDs allowed to control
SUDO_ONLY=true            # if true, only admins can control playback
LOG_LEVEL=INFO            # DEBUG/INFO/WARNING/ERROR
```

### Generate SESSION_STRING (locally)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install pyrogram tgcrypto
python generate_session.py
# Follow login prompts, then copy printed SESSION_STRING
```

---

## ▶️ Local Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill values
python -m src.main
```

---

## ☁️ Deploy on Railway
1. Push repo to GitHub.
2. Railway → **New Project → Deploy from GitHub** → select repo.
3. Set env variables (above). Add a **Volume** at `/data` (optional).
4. Deploy. Logs should show `Bot is online` and `PyTgCalls connected`.

---

## 🧰 Commands
- `/start` – hello + usage
- `/join` – join current group's voice chat
- `/leave` – leave voice chat
- `/play <url|query>` – play song (YouTube URL or text search)
- `/skip` – skip current
- `/pause` / `/resume`
- `/stop` – stop and clear queue
- `/queue` – show queue
- `/volume <0-200>` – set playback volume

> Make sure a voice chat is created in the group. Add bot and assistant user to the group; give mic permission to assistant user.

---

## Project Structure
```
.
├── Dockerfile
├── requirements.txt
├── .env.example
├── generate_session.py
└── src
    ├── main.py
    ├── player.py
    ├── queue.py
    ├── utils
    │   ├── ytdl.py
    │   └── logger.py
```

---

## Notes
- Searches pick first relevant YouTube result. You can customize filters in `ytdl.py`.
- If Railway audio is choppy, try smaller `buffer_size` or lower `audio_bitrate` in `player.py`.
- To restrict controls to admins only, set `SUDO_ONLY=true`.
