import os
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from gtts import gTTS
import yt_dlp
import aiohttp
import ffmpeg

# ---------- LOGGING ----------
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

# ---------- Init clients ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
pytg = PyTgCalls(app)

# ---------- Global states ----------
play_queue = asyncio.Queue()
playing_lock = asyncio.Lock()
tts_engine = "gtts"  # default
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)


# ---------- Helpers ----------
def yt_download(query: str) -> Optional[str]:
    outname = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir)).name
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outname,
        "quiet": True,
        "nocheckcertificate": True,
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


async def tts_gtts(text: str) -> Optional[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir))
    tmp.close()
    try:
        gTTS(text=text, lang="hi").save(tmp.name)
        return tmp.name
    except Exception as e:
        logger.error("gTTS error: %s", e)
        return None


async def tts_eleven(text: str) -> Optional[str]:
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        logger.error("ElevenLabs credentials missing")
        return None
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {"text": text, "voice_settings": {"stability": 0.4, "similarity_boost": 0.8}}
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir))
    tmp.close()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    with open(tmp.name, "wb") as f:
                        f.write(await resp.read())
                    return tmp.name
                else:
                    logger.error("ElevenLabs error: %s", await resp.text())
                    return None
    except Exception as e:
        logger.error("ElevenLabs exception: %s", e)
        return None


async def enqueue_and_play(filepath: str):
    await play_queue.put(filepath)
    if not playing_lock.locked():
        asyncio.create_task(player_worker())


async def player_worker():
    async with playing_lock:
        while not play_queue.empty():
            filepath = await play_queue.get()
            try:
                if GROUP_ID:
                    await pytg.join_group_call(
                        GROUP_ID,
                        AudioPiped(filepath),
                    )
                logger.info("Playing: %s", filepath)
                probe = ffmpeg.probe(filepath)
                duration = float(probe['format']['duration'])
                await asyncio.sleep(duration + 1)
                await pytg.leave_group_call(GROUP_ID)
            except Exception as e:
                logger.error("Playback error: %s", e)
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
                play_queue.task_done()


# ---------- Handlers ----------
@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def channel_text(_, msg: Message):
    text = msg.text.strip()
    if not text:
        return
    if tts_engine == "gtts":
        mp3 = await tts_gtts(text)
    else:
        mp3 = await tts_eleven(text)
    if mp3:
        await enqueue_and_play(mp3)


@app.on_message(filters.command("play") & filters.group)
async def play_cmd(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /play <song or YouTube URL>")
    query = " ".join(msg.command[1:])
    path = await asyncio.get_event_loop().run_in_executor(None, yt_download, query)
    if path:
        await enqueue_and_play(path)
        await msg.reply("Queued ✅")
    else:
        await msg.reply("Download failed ❌")


@app.on_message(filters.command("ttsengine") & filters.group)
async def change_engine(_, msg: Message):
    global tts_engine
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("gTTS", callback_data="engine_gtts"),
         InlineKeyboardButton("ElevenLabs", callback_data="engine_eleven")]
    ])
    await msg.reply("Choose TTS engine:", reply_markup=keyboard)


@app.on_callback_query()
async def cb_handler(_, cq):
    global tts_engine
    if cq.data == "engine_gtts":
        tts_engine = "gtts"
        await cq.message.edit("✅ TTS engine set to gTTS")
    elif cq.data == "engine_eleven":
        tts_engine = "eleven"
        await cq.message.edit("✅ TTS engine set to ElevenLabs")


# ---------- Main ----------
async def main():
    await app.start()
    await pytg.start()
    logger.info("Bot started! Waiting for commands...")
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
