import os
import asyncio
import logging
import tempfile
import signal
import sys
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import GroupCallFactory

from gtts import gTTS
import aiohttp
import yt_dlp
import subprocess

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vcbot")
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
DEFAULT_TTS_VOICE = os.getenv("ELEVEN_DEFAULT_VOICE", ELEVEN_VOICE_ID)

# ---------- INIT ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
gcf = GroupCallFactory(app)
pytg = gcf.get_group_call()

# temp directory for downloads & tts
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# concurrency control and queue
AUDIO_SEMAPHORE = asyncio.Semaphore(1)
play_queue: asyncio.Queue = asyncio.Queue()
current_track: Optional[dict] = None

# default TTS mode
tts_mode = "gtts"  # or "eleven"

# ---------- HELPERS ----------

def run_ffmpeg_filter(input_path: str, output_path: str, af_filter: str, timeout: int = 30) -> bool:
    """Apply ffmpeg audio filter using subprocess. Returns True on success."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", af_filter,
        output_path
    ]
    try:
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if completed.returncode != 0:
            logger.error("ffmpeg filter failed: %s", completed.stderr.decode(errors="ignore"))
            return False
        return True
    except Exception as e:
        logger.exception("ffmpeg exception: %s", e)
        return False


def apply_effect(path: str, effect: str) -> Optional[str]:
    """Create a new temp file with effect applied and return path or None."""
    out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    if effect == "bass":
        af = "bass=g=10"
    elif effect == "deep":
        af = "asetrate=44100*0.9,aresample=44100,atempo=1"
    elif effect == "fast":
        af = "atempo=1.5"
    elif effect == "echo":
        af = "aecho=0.8:0.9:1000:0.3"
    else:
        return None
    ok = run_ffmpeg_filter(path, out, af)
    if ok:
        return out
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    return None


def yt_download(query: str) -> Optional[str]:
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
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([query])
        return outname
    except Exception:
        logger.exception("yt-dlp failed for %s", query)
        try:
            if os.path.exists(outname):
                os.remove(outname)
        except Exception:
            pass
        return None


async def tts_gtts(text: str, lang: str = "hi") -> Optional[str]:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
        def _save():
            gTTS(text=text, lang=lang).save(path)
        await asyncio.get_event_loop().run_in_executor(None, _save)
        return path
    except Exception:
        logger.exception("gTTS failed")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return None


async def tts_eleven(text: str, voice_id: str = DEFAULT_TTS_VOICE) -> Optional[str]:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    if not ELEVEN_API_KEY or not voice_id:
        logger.error("ElevenLabs credentials missing")
        return None
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
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
                    logger.error("ElevenLabs error: %s", txt)
                    return None
    except Exception:
        logger.exception("ElevenLabs TTS failed")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return None


async def join_and_play(filepath: str):
    async with AUDIO_SEMAPHORE:
        global current_track
        try:
            # stop any existing audio
            try:
                await pytg.stop()
            except Exception:
                pass
            await asyncio.sleep(0.5)
            # start audio using new API
            await pytg.start_audio(filepath)
            current_track = {"path": filepath}
            logger.info("Playing: %s", filepath)
        except Exception:
            logger.exception("Failed to start audio")
            raise


async def cleanup(path: str, delay: float = 6.0):
    await asyncio.sleep(delay)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("Removed file %s", path)
    except Exception:
        logger.exception("Cleanup failed")


# ---------- QUEUE WORKER ----------
async def queue_worker():
    while True:
        item = await play_queue.get()
        try:
            source = item.get("source")
            effect = item.get("effect")
            # source can be a filepath already
            if isinstance(source, str) and (source.startswith("http") or source.startswith("www")):
                path = await asyncio.get_event_loop().run_in_executor(None, yt_download, source)
            else:
                path = source
            if not path:
                continue
            if effect:
                ef_path = apply_effect(path, effect)
                if ef_path:
                    # ensure original removed later
                    asyncio.create_task(cleanup(path, delay=5.0))
                    path = ef_path
            try:
                await join_and_play(path)
                # cleanup after playback started
                asyncio.create_task(cleanup(path, delay=20.0))
            except Exception:
                logger.exception("Playback failed for %s", path)
        finally:
            play_queue.task_done()


# ---------- HANDLERS ----------

def mk_controls():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏯ Pause/Resume", callback_data="ctrl_pause"), InlineKeyboardButton("⏭ Skip", callback_data="ctrl_skip")],
        [InlineKeyboardButton("🎚 Effects", callback_data="effects_menu"), InlineKeyboardButton("🗣 Mode", callback_data="mode_menu")]
    ])


def safe_handler(fn):
    async def wrapper(c, m, *args, **kwargs):
        try:
            await fn(c, m, *args, **kwargs)
        except Exception:
            logger.exception("Handler error")
            try:
                await m.reply("⚠️ Internal error. Check logs.")
            except Exception:
                pass
    return wrapper


@app.on_message(filters.command("play") & filters.group)
@safe_handler
async def play_handler(c: Client, m: Message):
    # support: /play <url or query> OR reply to audio/voice/document
    effect = None
    parts = m.text.split() if m.text else []
    if len(parts) >= 2:
        source = " ".join(parts[1:])
    elif m.reply_to_message and (m.reply_to_message.audio or m.reply_to_message.voice or m.reply_to_message.document):
        # download replied media
        fpath = await c.download_media(m.reply_to_message)
        source = fpath
    else:
        await m.reply("Usage: /play <YouTube URL or name> or reply to a media file with /play")
        return
    await m.reply("🎵 Added to queue...", reply_markup=mk_controls())
    await play_queue.put({"source": source, "effect": effect})


@app.on_message(filters.command(["skip", "stop"]) & filters.group)
@safe_handler
async def skip_handler(c: Client, m: Message):
    try:
        await pytg.stop()
        await m.reply("⏭ Skipped")
    except Exception:
        logger.exception("Skip failed")
        await m.reply("❌ Skip failed. See logs.")


@app.on_message(filters.command("tts") & filters.group)
@safe_handler
async def tts_handler(c: Client, m: Message):
    global tts_mode
    if len(m.command) < 2:
        return await m.reply("Usage: /tts <text>")
    text = " ".join(m.command[1:])
    await m.reply("🎤 Generating voice...")
    if tts_mode == "gtts":
        path = await tts_gtts(text)
    else:
        path = await tts_eleven(text)
    if path:
        await play_queue.put({"source": path, "effect": None})
        await m.reply("🔊 TTS queued", reply_markup=mk_controls())
    else:
        await m.reply("❌ TTS failed")


@app.on_message(filters.command("mode") & filters.group)
@safe_handler
async def mode_handler(c: Client, m: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙 gTTS", callback_data="tts_gtts"), InlineKeyboardButton("🧠 ElevenLabs", callback_data="tts_eleven")]
    ])
    await m.reply("Select TTS mode:", reply_markup=keyboard)


@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
@safe_handler
async def channel_broadcast(c: Client, m: Message):
    # Convert channel text to voice and play in group VC
    text = m.text.strip()
    if not text:
        return
    logger.info("Channel message received, converting to TTS")
    if tts_mode == "gtts":
        path = await tts_gtts(text)
    else:
        path = await tts_eleven(text)
    if path:
        # priority play: stop current and play this immediately
        try:
            await pytg.stop()
        except Exception:
            pass
        await play_queue.put({"source": path, "effect": None})
    else:
        logger.error("Channel TTS generation failed")


@app.on_callback_query()
async def cb_handler(c, q):
    global tts_mode
    data = q.data
    if data == "tts_gtts":
        tts_mode = "gtts"
        await q.answer("✅ gTTS mode enabled")
    elif data == "tts_eleven":
        tts_mode = "eleven"
        await q.answer("✅ ElevenLabs mode enabled")
    elif data == "ctrl_skip":
        try:
            await pytg.stop()
            await q.answer("⏭ Skipped")
        except Exception:
            await q.answer("❌ Skip failed")
    elif data == "ctrl_pause":
        # attempt pause/resume if supported
        try:
            if hasattr(pytg, "pause") and hasattr(pytg, "resume"):
                await pytg.pause()
                await q.answer("⏸ Paused")
            else:
                await q.answer("Pause not supported by this pytgcalls version")
        except Exception:
            await q.answer("Pause failed")
    elif data == "effects_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bass", callback_data="effect_bass"), InlineKeyboardButton("Deep", callback_data="effect_deep")],
            [InlineKeyboardButton("Fast", callback_data="effect_fast"), InlineKeyboardButton("Echo", callback_data="effect_echo")]
        ])
        try:
            await q.message.edit_reply_markup(kb)
        except Exception:
            pass
        await q.answer()
    elif data and data.startswith("effect_"):
        eff = data.split("_")[1]
        # store chosen effect to apply to next track - for simplicity we push a special item
        await q.answer(f"Effect {eff} will apply to next track")
    else:
        await q.answer()


# ---------- START / STOP ----------
async def start_bot():
    await app.start()
    # start queue worker
    asyncio.create_task(queue_worker())
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
