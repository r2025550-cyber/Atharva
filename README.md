# Telegram VC Hindi TTS Bot

This bot listens to text messages in a specified channel and plays them as Hindi TTS in a group's voice chat.

## Features
- Convert Hindi text to speech using gTTS (free).
- Auto-play audio into group VC using PyTgCalls.

## Setup

### 1. Environment Variables
Create `.env` or set in Railway/Heroku:

- API_ID: from my.telegram.org
- API_HASH: from my.telegram.org
- SESSION_STRING: generated with gen.py
- CHANNEL_ID: channel username or ID
- GROUP_ID: group ID or @username

### 2. Run locally (Termux/Linux)
```bash
pip install -r requirements.txt
python bot.py
```

### 3. Deploy to Railway
- Push this project to GitHub.
- Connect GitHub repo in Railway.
- Add environment variables in Railway dashboard.
- Deploy and enjoy!
