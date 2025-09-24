import os
import asyncio
import logging
import tempfile
import subprocess
import requests
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import AudioPiped
except Exception:
    from pytgcalls.types.input_stream import AudioPiped
    from pytgcalls import PyTgCalls

import yt_dlp
import ffmpeg
from gtts import gTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vcbot")

# ---------- ENV ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "")

TTS_ENGINE = "eleven" if ELEVEN_API_KEY else "gtts"
VOICE_MODE = "normal"

# ---------- Init ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
pytg = PyTgCalls(app)

play_queue = asyncio.Queue()
playing_lock = asyncio.Lock()
current_track = None
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------
def safe_fname(prefix="aud", ext=".mp3") -> str:
    f = tempfile.NamedTemporaryFile(prefix=prefix, suffix=ext, delete=False, dir=str(temp_dir))
    f.close()
    return f.name

async def tts_gtts(text: str, lang="hi") -> Optional[str]:
    fn = safe_fname("tts_gtts_", ".mp3")
    try:
        gTTS(text=text, lang=lang).save(fn)
        return fn
    except Exception as e:
        logger.error("gTTS error: %s", e)
        return None

async def tts_elevenlabs(text: str) -> Optional[str]:
    fn = safe_fname("tts_eleven_", ".mp3")
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
        headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
        data = {"text": text, "voice_settings": {"stability": 0.6, "similarity_boost": 0.7}}
        r = requests.post(url, headers=headers, json=data, timeout=30)
        if r.status_code == 200:
            with open(fn, "wb") as f:
                f.write(r.content)
            return fn
        else:
            logger.error("ElevenLabs error: %s", r.text)
            return None
    except Exception as e:
        logger.error("ElevenLabs exception: %s", e)
        return None

async def tts_to_file(text: str) -> Optional[str]:
    global TTS_ENGINE
    if TTS_ENGINE == "eleven" and ELEVEN_API_KEY:
        f = await tts_elevenlabs(text)
        if f: return f
    return await tts_gtts(text)

def apply_voice_effect(input_file: str, mode: str) -> str:
    if mode == "normal":
        return input_file
    out = safe_fname(f"fx_{mode}_", ".mp3")
    filters = {
        "dark": "asetrate=44100*0.9,aresample=44100,lowpass=f=3000,volume=1.1",
        "fighter": "asetrate=44100*0.85,aresample=44100,volume=1.3,lowpass=f=3500",
        "robot": "afftfilt=real='sin(0.01*PI*Y)'",
        "echo": "aecho=0.8:0.9:1000:0.3",
        "funny": "asetrate=44100*1.2,aresample=44100"
    }
    flt = filters.get(mode)
    if not flt: return input_file
    try:
        cmd = ["ffmpeg", "-y", "-i", input_file, "-af", flt, out]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return out
    except Exception as e:
        logger.error("Effect error: %s", e)
        return input_file

async def enqueue_and_play(filepath: str, title=""):
    await play_queue.put((filepath, title))
    if not playing_lock.locked():
        asyncio.create_task(player_worker())

async def player_worker():
    global current_track
    async with playing_lock:
        while not play_queue.empty():
            filepath, title = await play_queue.get()
            current_track = title
            try:
                await pytg.join_group_call(GROUP_ID, AudioPiped(filepath))
                dur = float(ffmpeg.probe(filepath)['format']['duration'])
                await asyncio.sleep(dur + 1)
                await pytg.leave_group_call(GROUP_ID)
            except Exception as e:
                logger.error("Playback error: %s", e)
            finally:
                if os.path.exists(filepath): os.remove(filepath)
                play_queue.task_done()
        current_track = None

def controls_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸️ Pause", callback_data="pause"),
         InlineKeyboardButton("▶️ Resume", callback_data="resume")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="skip"),
         InlineKeyboardButton("⏹️ Stop", callback_data="stop")],
        [InlineKeyboardButton("📜 Queue", callback_data="queue")]
    ])

def voice_mode_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎤 Normal", callback_data="vm_normal"),
         InlineKeyboardButton("⚡ Dark", callback_data="vm_dark")],
        [InlineKeyboardButton("🥊 Fighter", callback_data="vm_fighter"),
         InlineKeyboardButton("🤖 Robot", callback_data="vm_robot")],
        [InlineKeyboardButton("🎶 Echo", callback_data="vm_echo"),
         InlineKeyboardButton("😂 Funny", callback_data="vm_funny")]
    ])

@app.on_callback_query()
async def on_callback(client, cq):
    global VOICE_MODE
    if cq.data == "pause":
        await pytg.pause_stream(GROUP_ID)
        await cq.answer("⏸️ Paused")
    elif cq.data == "resume":
        await pytg.resume_stream(GROUP_ID)
        await cq.answer("▶️ Resumed")
    elif cq.data == "skip":
        if not play_queue.empty():
            play_queue.get_nowait(); play_queue.task_done()
            await pytg.leave_group_call(GROUP_ID)
            await cq.answer("⏭️ Skipped")
    elif cq.data == "stop":
        while not play_queue.empty():
            play_queue.get_nowait(); play_queue.task_done()
        await pytg.leave_group_call(GROUP_ID)
        await cq.answer("⏹️ Stopped")
    elif cq.data == "queue":
        qlist = list(play_queue._queue)
        text = "📜 **Queue:**\n"
        if current_track: text += f"▶️ {current_track}\n"
        for i, (_, t) in enumerate(qlist, 1): text += f"{i}. {t}\n"
        await cq.message.reply_text(text if text.strip() else "Queue empty.")
    elif cq.data.startswith("vm_"):
        VOICE_MODE = cq.data.replace("vm_", "")
        await cq.message.edit_text(f"✅ Voice mode set to **{VOICE_MODE}**")

@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def on_channel_text(client, message: Message):
    global VOICE_MODE
    text = message.text.strip()
    if not text: return
    mp3 = await tts_to_file(text)
    if mp3:
        processed = apply_voice_effect(mp3, VOICE_MODE)
        await enqueue_and_play(processed, f"TTS: {text[:30]}")
        await message.reply_text("🎙️ Playing TTS", reply_markup=voice_mode_markup())

@app.on_message(filters.command("play") & filters.group)
async def cmd_play(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /play <yt link or search>")
        return
    query = " ".join(message.command[1:])
    fn = safe_fname("yt_", ".mp3")
    ydl_opts = {
        "format": "bestaudio/best", "outtmpl": fn, "quiet": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([query])
        await enqueue_and_play(fn, query)
        await message.reply_text(f"Queued ✅ {query}", reply_markup=controls_markup())
    except Exception as e:
        await message.reply_text(f"Download error: {e}")

# ---------- Main ----------
async def main():
    await app.start()
    await pytg.start()
    logger.info("Bot running...")
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
