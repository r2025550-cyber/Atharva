# Telegram Advanced Music Bot (TgCaller edition) — Railway Ready 🚀

Stable Telegram **music bot** for **group voice chats**, built on **TgCaller** (stable alternative to fragile PyTgCalls dev builds).

## Features
- /join, /leave
- /play <query|url> (YouTube supported)
- /skip, /stop, /pause, /resume
- /queue, /np
- /volume 0-200
- Admin-only controls with SUDO_ONLY + ADMINS

## Deploy on Railway
1) Push to GitHub. 2) Deploy from GitHub. 3) Add env vars from `.env.example`. 4) Deploy.

## Local run
```
pip install -r requirements.txt
python -m src.generate_session    # get SESSION_STRING (needs API_ID/API_HASH env)
python -m src.main
```
