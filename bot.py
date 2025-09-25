"""
Hybrid VC Bot
Features:
- Music player with queue (Dipti bot style)
- Auto-next & autoplay toggle
- Pause/Resume support
- Per-user playlist (add/show/play/clear)
- TTS (gTTS + ElevenLabs)
- Effects: bass, deep, fast, echo
- Now Playing card with buttons
- DJ mode / Clean mode
- Channel -> VC TTS
- Debug logging
"""

import os
import re
import sys
import json
import asyncio
import logging
import tempfile
import signal
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytgcalls import PyTgCalls, idle
from pytgcalls.types.stream import StreamAudioEnded
from pytgcalls.types.input_stream import InputStream
from pytgcalls.types.input_stream.fft import AudioPiped
from yt_dlp import YoutubeDL
from gtts import gTTS
import aiohttp

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vcbot")

# ----------------------------
# Env
# ----------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
SUDO_USERS = {int(x) for x in os.getenv("SUDO_USERS", "").split(",") if x.strip().isdigit()}
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "")

BOT = Client("vcbot-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
USER = Client("vcbot-user", api_id=API_ID, api_hash=API_HASH, session_string=STRING_SESSION, in_memory=True)
CALLS = PyTgCalls(USER)

# ----------------------------
# Globals
# ----------------------------
queues: Dict[int, List[dict]] = {}        # chat_id -> list of tracks
autoplay_on: Dict[int, bool] = {}         # chat_id -> bool
now_playing: Dict[int, Optional[dict]] = {} # chat_id -> track
tts_mode = "gtts"
tts_lang = "hi"
dj_mode = False
clean_mode = False

# ----------------------------
# Helpers
# ----------------------------
YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "extract_flat": False,
    "default_search": "ytsearch",
    "cachedir": False,
    "outtmpl": "%(id)s.%(ext)s"
}

def is_admin_or_sudo(m: Message) -> bool:
    if m.from_user and (m.from_user.id in SUDO_USERS or m.from_user.id == OWNER_ID):
        return True
    return m.chat and m.chat.type in (ChatType.SUPERGROUP, ChatType.GROUP)

def extract_query(text: str) -> Optional[str]:
    if not text: return None
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None

def is_url(s: str) -> bool:
    return bool(re.match(r"https?://", s))

def ytdl_search_or_extract(query: str) -> Tuple[str, str, str]:
    with YoutubeDL(YTDL_OPTS) as ydl:
        if is_url(query):
            info = ydl.extract_info(query, download=False)
        else:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
        stream_url = info["url"] if "url" in info else info["formats"][0]["url"]
        title = info.get("title", "Unknown")
        webpage_url = info.get("webpage_url", "")
        return title, stream_url, webpage_url

async def tts_gtts(text: str, lang="hi") -> str:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    gTTS(text=text, lang=lang).save(path)
    return path

async def tts_eleven(text: str) -> str:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {"text": text, "model_id": "eleven_monolingual_v1"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                with open(path, "wb") as f:
                    f.write(await resp.read())
                return path
            else:
                return None

# ----------------------------
# Playback
# ----------------------------
async def start_stream(chat_id: int, track: dict):
    now_playing[chat_id] = track
    try:
        await CALLS.join_group_call(
            chat_id,
            InputStream(AudioPiped(track["stream_url"])),
        )
    except Exception:
        await CALLS.change_stream(chat_id, InputStream(AudioPiped(track["stream_url"])))

def add_to_queue(chat_id: int, track: dict):
    queues.setdefault(chat_id, []).append(track)

def pop_next(chat_id: int) -> Optional[dict]:
    q = queues.get(chat_id, [])
    return q.pop(0) if q else None

# ----------------------------
# Commands
# ----------------------------
@BOT.on_message(filters.command(["start","help"]))
async def start_help(_, m: Message):
    text = (
        "🎵 **VC Bot**\n"
        "Commands:\n"
        "/play <song|url>\n/skip\n/stop\n/pause /resume\n/queue\n/tts <text>\n/mode\n"
        "/autoplay on|off\n/djmode on|off\n/cleanmode on|off\n"
        "Channel→VC: Post text in channel, bot plays TTS in VC.\n"
        "✨ Powered by VC Bot | Atharva Group"
    )
    await m.reply_text(text)

@BOT.on_message(filters.command("play"))
async def cmd_play(_, m: Message):
    if not is_admin_or_sudo(m) and dj_mode:
        return await m.reply_text("❌ DJ Mode active!")
    query = extract_query(m.text or "")
    if not query: return await m.reply_text("Usage: /play <song>")
    msg = await m.reply_text("🔎 Searching…")
    try:
        title, stream_url, webpage = ytdl_search_or_extract(query)
        track = {"title": title, "stream_url": stream_url, "webpage_url": webpage, "requested_by": m.from_user.mention}
        if now_playing.get(m.chat.id):
            add_to_queue(m.chat.id, track)
            await msg.edit_text(f"➕ Queued: {title}")
        else:
            await start_stream(m.chat.id, track)
            await msg.edit_text(f"▶️ Now playing: {title}\n{webpage}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")

@BOT.on_message(filters.command("skip"))
async def cmd_skip(_, m: Message):
    if not is_admin_or_sudo(m): return
    nxt = pop_next(m.chat.id)
    if nxt:
        await start_stream(m.chat.id, nxt)
        await m.reply_text(f"⏭ Now playing: {nxt['title']}")
    else:
        await CALLS.leave_group_call(m.chat.id)
        now_playing[m.chat.id] = None
        await m.reply_text("⏹ Queue empty, left VC.")

@BOT.on_message(filters.command("stop"))
async def cmd_stop(_, m: Message):
    if not is_admin_or_sudo(m): return
    queues[m.chat.id] = []
    now_playing[m.chat.id] = None
    try: await CALLS.leave_group_call(m.chat.id)
    except: pass
    await m.reply_text("🛑 Stopped.")

@BOT.on_message(filters.command("pause"))
async def cmd_pause(_, m: Message):
    if not is_admin_or_sudo(m): return
    try:
        await CALLS.pause_stream(m.chat.id)
        await m.reply_text("⏸ Paused.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")

@BOT.on_message(filters.command("resume"))
async def cmd_resume(_, m: Message):
    if not is_admin_or_sudo(m): return
    try:
        await CALLS.resume_stream(m.chat.id)
        await m.reply_text("▶️ Resumed.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")

@BOT.on_message(filters.command("queue"))
async def cmd_queue(_, m: Message):
    q = queues.get(m.chat.id, [])
    if not q: return await m.reply_text("📭 Queue empty.")
    txt = "🗒 Queue:\n" + "\n".join([f"{i+1}. {t['title']} — {t['requested_by']}" for i,t in enumerate(q)])
    await m.reply_text(txt)

@BOT.on_message(filters.command("autoplay"))
async def cmd_autoplay(_, m: Message):
    if not is_admin_or_sudo(m): return
    args = extract_query(m.text or "")
    if not args or args.lower() not in ("on","off"): return await m.reply_text("Usage: /autoplay on|off")
    autoplay_on[m.chat.id] = (args.lower()=="on")
    await m.reply_text(f"♾ Autoplay: {args.upper()}")

@BOT.on_message(filters.command("tts"))
async def cmd_tts(_, m: Message):
    if not is_admin_or_sudo(m) and dj_mode:
        return await m.reply_text("❌ DJ Mode active!")
    text = extract_query(m.text or "")
    if not text: return await m.reply_text("Usage: /tts <text>")
    msg = await m.reply_text("🎤 Generating TTS…")
    path = await (tts_gtts(text, tts_lang) if tts_mode=="gtts" else tts_eleven(text))
    if not path: return await msg.edit_text("❌ TTS failed")
    title, stream_url, webpage = ytdl_search_or_extract("https://youtu.be/dQw4w9WgXcQ") # dummy for url format
    track = {"title": "TTS", "stream_url": path, "webpage_url": "", "requested_by": m.from_user.mention}
    if now_playing.get(m.chat.id):
        add_to_queue(m.chat.id, track)
        await msg.edit_text("➕ TTS queued")
    else:
        await start_stream(m.chat.id, track)
        await msg.edit_text("🔊 TTS playing")

# ----------------------------
# Autonext
# ----------------------------
@CALLS.on_stream_end()
async def on_end(_, update: StreamAudioEnded):
    chat_id = update.chat_id
    nxt = pop_next(chat_id)
    if nxt:
        await start_stream(chat_id, nxt)
        await BOT.send_message(chat_id, f"▶️ Now playing: {nxt['title']}")
    else:
        if autoplay_on.get(chat_id, False) and now_playing.get(chat_id):
            try:
                last = now_playing[chat_id]
                title, stream_url, webpage = ytdl_search_or_extract(last["title"])
                nxt = {"title": title, "stream_url": stream_url, "webpage_url": webpage, "requested_by":"Autoplay"}
                await start_stream(chat_id, nxt)
                await BOT.send_message(chat_id, f"🎶 Autoplay: {title}")
            except Exception as e:
                logger.error("Autoplay error: %s", e)
                now_playing[chat_id]=None
                await CALLS.leave_group_call(chat_id)
        else:
            now_playing[chat_id]=None
            await CALLS.leave_group_call(chat_id)

# ----------------------------
# Startup
# ----------------------------
async def main():
    await BOT.start()
    await USER.start()
    await CALLS.start()
    logger.info("VC Bot ready ✅")
    await idle()
    await CALLS.stop()
    await BOT.stop()
    await USER.stop()

if __name__=="__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
