import os
import asyncio
import logging
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped

from gtts import gTTS
import aiohttp
import yt_dlp
import ffmpeg

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vcbot")

# ---------- ENV ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))   # -100123..
GROUP_ID = int(os.getenv("GROUP_ID", "0"))       # -100123..
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "")

# ---------- INIT ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
pytg = PyTgCalls(app)

temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

tts_mode = "gtts"  # default

# ---------- HELPERS ----------
def yt_download(query: str) -> str | None:
    """Download YouTube audio"""
    outname = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outname,
        "quiet": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
        return outname
    except Exception as e:
        logger.error("yt-dlp error: %s", e)
        return None

async def tts_gtts(text: str, lang="hi") -> str | None:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
        gTTS(text=text, lang=lang).save(path)
        return path
    except Exception as e:
        logger.error("gTTS error: %s", e)
        return None

async def tts_eleven(text: str) -> str | None:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
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
                    logger.error("ElevenLabs error: %s", await resp.text())
                    return None
    except Exception as e:
        logger.error("ElevenLabs exception: %s", e)
        return None

async def play_file(filepath: str):
    try:
        await pytg.join_group_call(
            GROUP_ID,
            AudioPiped(filepath)
        )
    except Exception as e:
        logger.error("Play error: %s", e)

# ---------- HANDLERS ----------

@app.on_message(filters.command("play") & filters.group)
async def play_handler(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply("Usage: /play <song name or YouTube URL>")
    query = " ".join(m.command[1:])
    await m.reply("🎵 Downloading...")
    path = await asyncio.get_event_loop().run_in_executor(None, yt_download, query)
    if path:
        await play_file(path)
        await m.reply("▶️ Now Playing")
    else:
        await m.reply("❌ Download failed")

@app.on_message(filters.command("skip") & filters.group)
async def skip_handler(c: Client, m: Message):
    try:
        await pytg.leave_group_call(GROUP_ID)
        await m.reply("⏭ Skipped")
    except Exception as e:
        await m.reply(f"Skip error: {e}")

@app.on_message(filters.command("tts") & filters.group)
async def tts_handler(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply("Usage: /tts <text>")
    text = " ".join(m.command[1:])
    await m.reply("🎤 Generating voice...")
    path = await (tts_gtts(text) if tts_mode == "gtts" else tts_eleven(text))
    if path:
        await play_file(path)
        await m.reply("🔊 TTS Playing")
    else:
        await m.reply("❌ TTS failed")

@app.on_message(filters.command("mode") & filters.group)
async def mode_handler(c: Client, m: Message):
    global tts_mode
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙 gTTS", callback_data="tts_gtts"),
         InlineKeyboardButton("🧠 ElevenLabs", callback_data="tts_eleven")]
    ])
    await m.reply("Select TTS mode:", reply_markup=keyboard)

@app.on_callback_query()
async def cb_handler(c, q):
    global tts_mode
    if q.data == "tts_gtts":
        tts_mode = "gtts"
        await q.answer("✅ gTTS mode enabled")
    elif q.data == "tts_eleven":
        tts_mode = "eleven"
        await q.answer("✅ ElevenLabs mode enabled")

# ---------- MAIN ----------
async def main():
    await app.start()
    await pytg.start()
    logger.info("Bot started ✅")
    await asyncio.get_event_loop().create_future()

if __name__ == "__main__":
    asyncio.run(main())
