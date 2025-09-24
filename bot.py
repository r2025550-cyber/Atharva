import os
import asyncio
import logging
import tempfile
import signal
import sys
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import GroupCallFactory

from gtts import gTTS
import aiohttp
import yt_dlp

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vcbot")

# Also log errors to file for post-mortem
err_handler = logging.FileHandler("bot_error.log")
err_handler.setLevel(logging.ERROR)
logger.addHandler(err_handler)

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
gcf = GroupCallFactory(app)
pytg = gcf.get_group_call()

# temp directory for downloads & tts
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# concurrency control - tunable
AUDIO_SEMAPHORE = asyncio.Semaphore(2)

# default TTS mode
tts_mode = "gtts"  # or "eleven"

# ---------- HELPERS ----------

def yt_download(query: str, timeout: int = 60) -> str | None:
    outname = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outname,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "noplaylist": True,
        "ignoreerrors": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
        return outname
    except Exception as e:
        logger.error("yt-dlp error: %s", e, exc_info=True)
        try:
            if os.path.exists(outname):
                os.remove(outname)
        except Exception:
            pass
        return None


async def tts_gtts(text: str, lang="hi") -> str | None:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
        def _save():
            gTTS(text=text, lang=lang).save(path)
        await asyncio.get_event_loop().run_in_executor(None, _save)
        return path
    except Exception as e:
        logger.error("gTTS error: %s", e, exc_info=True)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return None


async def tts_eleven(text: str) -> str | None:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        logger.error("ElevenLabs credentials not set")
        return None
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
        headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
        payload = {"text": text, "model_id": "eleven_monolingual_v1"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    with open(path, "wb") as f:
                        f.write(await resp.read())
                    return path
                else:
                    txt = await resp.text()
                    logger.error("ElevenLabs error status=%s: %s", resp.status, txt)
                    return None
    except Exception as e:
        logger.error("ElevenLabs exception: %s", e, exc_info=True)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return None


async def safe_play(filepath: str):
    async with AUDIO_SEMAPHORE:
        try:
            await pytg.start_audio(filepath)
        except Exception as e:
            logger.error("Play error: %s", e, exc_info=True)
            raise


async def cleanup_file(path: str, delay: float = 2.0):
    await asyncio.sleep(delay)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("Removed temp file: %s", path)
    except Exception:
        logger.exception("Failed removing temp file")


# ---------- HANDLERS ----------

def safe_handler(fn):
    async def wrapper(c, m, *args, **kwargs):
        try:
            await fn(c, m, *args, **kwargs)
        except Exception as e:
            logger.error("Unhandled exception in handler: %s", e, exc_info=True)
            try:
                await m.reply("⚠️ An internal error occurred. Check bot logs.")
            except Exception:
                pass
    return wrapper


@app.on_message(filters.command("play") & filters.group)
@safe_handler
async def play_handler(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply("Usage: /play <song name or YouTube URL>")
    query = " ".join(m.command[1:])
    await m.reply("🎵 Downloading...")
    path = await asyncio.get_event_loop().run_in_executor(None, yt_download, query)
    if path:
        try:
            await safe_play(path)
            await m.reply("▶️ Now Playing")
            asyncio.create_task(cleanup_file(path, delay=5.0))
        except Exception:
            await m.reply("❌ Failed to play the audio. See logs.")
    else:
        await m.reply("❌ Download failed")


@app.on_message(filters.command("skip") & filters.group)
@safe_handler
async def skip_handler(c: Client, m: Message):
    try:
        await pytg.stop()
        await m.reply("⏭ Skipped")
    except Exception as e:
        logger.error("Skip error: %s", e, exc_info=True)
        await m.reply("❌ Skip failed. See logs.")


@app.on_message(filters.command("tts") & filters.group)
@safe_handler
async def tts_handler(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply("Usage: /tts <text>")
    text = " ".join(m.command[1:]).strip()
    if not text:
        return await m.reply("Please provide text for TTS.")
    await m.reply("🎤 Generating voice...")
    if tts_mode == "gtts":
        path = await tts_gtts(text)
    else:
        path = await tts_eleven(text)
    if path:
        try:
            await safe_play(path)
            await m.reply("🔊 TTS Playing")
            asyncio.create_task(cleanup_file(path, delay=5.0))
        except Exception:
            await m.reply("❌ Failed to play TTS. See logs.")
    else:
        await m.reply("❌ TTS failed")


@app.on_message(filters.command("mode") & filters.group)
@safe_handler
async def mode_handler(c: Client, m: Message):
    global tts_mode
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙 gTTS", callback_data="tts_gtts"),
         InlineKeyboardButton("🧠 ElevenLabs", callback_data="tts_eleven")]
    ])
    await m.reply("Select TTS mode:", reply_markup=keyboard)


@app.on_callback_query()
@safe_handler
async def cb_handler(c, q):
    global tts_mode
    if q.data == "tts_gtts":
        tts_mode = "gtts"
        await q.answer("✅ gTTS mode enabled")
    elif q.data == "tts_eleven":
        tts_mode = "eleven"
        await q.answer("✅ ElevenLabs mode enabled")


# ---------- START / STOP ----------

async def start_bot():
    await app.start()
    logger.info("Bot started ✅")


async def stop_bot():
    try:
        await pytg.stop()
    except Exception:
        pass
    try:
        await app.stop()
    except Exception:
        pass
    logger.info("Bot stopped")


def _signal_handler(sig, frame):
    logger.info("Signal received: %s, shutting down...", sig)
    asyncio.create_task(stop_bot())


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def main():
    await start_bot()
    await asyncio.get_event_loop().create_future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
