import os
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from gtts import gTTS
import yt_dlp
import aiohttp
import ffmpeg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vcbot")

# ---------- ENV ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))   # numeric like -100...
GROUP_ID = int(os.getenv("GROUP_ID", "0"))       # numeric like -100...

# ---------- Init clients ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
pytg = PyTgCalls(app)

# ---------- Playback queue ----------
play_queue = asyncio.Queue()
playing_lock = asyncio.Lock()
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------
async def download_file_from_message(msg: Message) -> Optional[str]:
    if msg.audio or msg.document or msg.voice:
        media = msg.audio or msg.document or msg.voice
        fname = f"{temp_dir}/{media.file_id}_{media.file_name or 'audio'}.mp3"
        try:
            logger.info("Downloading media...")
            await msg.download(file_name=fname)
            return fname
        except Exception as e:
            logger.error("Download failed: %s", e)
    return None

def yt_download_to_file(query: str) -> Optional[str]:
    outname = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir)).name
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outname,
        "quiet": True,
        "nocheckcertificate": True,
        "ffmpeg_location": shutil.which("ffmpeg") or None,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("yt-dlp downloading: %s", query)
            ydl.download([query])
        return outname
    except Exception as e:
        logger.error("yt-dlp error: %s", e)
        if os.path.exists(outname):
            os.remove(outname)
        return None

async def tts_to_file(text: str, lang: str = "hi") -> Optional[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir))
    tmp.close()
    try:
        tts = gTTS(text=text, lang=lang)
        tts.save(tmp.name)
        return tmp.name
    except Exception as e:
        logger.error("gTTS error: %s", e)
        os.remove(tmp.name)
        return None

async def enqueue_and_maybe_play(filepath: str, title: str = None):
    await play_queue.put((filepath, title or filepath))
    if not playing_lock.locked():
        asyncio.create_task(player_worker())

async def player_worker():
    async with playing_lock:
        while not play_queue.empty():
            filepath, title = await play_queue.get()
            logger.info("Now playing: %s", title)
            try:
                await pytg.join_group_call(
                    GROUP_ID,
                    AudioPiped(filepath)
                )
                try:
                    probe = ffmpeg.probe(filepath)
                    duration = float(probe['format']['duration'])
                except Exception:
                    duration = 0
                await asyncio.sleep(max(2, duration))
                await pytg.leave_group_call(GROUP_ID)
            except Exception as e:
                logger.error("Playback error: %s", e)
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
                play_queue.task_done()

# ---------- Handlers ----------
@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def on_channel_text(client: Client, message: Message):
    text = message.text.strip()
    if not text:
        return
    logger.info("Channel text received for TTS")
    mp3 = await tts_to_file(text, lang="hi")
    if mp3:
        await enqueue_and_maybe_play(mp3, title=f"TTS: {text[:30]}")

@app.on_message(filters.chat(CHANNEL_ID) & (filters.audio | filters.voice | filters.document))
async def on_channel_media(client: Client, message: Message):
    logger.info("Channel media received")
    path = await download_file_from_message(message)
    if path:
        await enqueue_and_maybe_play(path, title="ChannelAudio")

@app.on_message(filters.command("play") & (filters.chat(CHANNEL_ID) | filters.group))
async def cmd_play(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /play <YouTube URL or search>")
        return
    query = " ".join(message.command[1:])
    await message.reply_text(f"Downloading: {query}")
    if query.startswith("http://") or query.startswith("https://"):
        target = query
    else:
        target = f"ytsearch:{query}"
    loop = asyncio.get_event_loop()
    mp3_path = await loop.run_in_executor(None, yt_download_to_file, target)
    if mp3_path:
        await message.reply_text("Queued ✅")
        await enqueue_and_maybe_play(mp3_path, title=query)
    else:
        await message.reply_text("Download failed ❌")

@app.on_message(filters.command("skip") & filters.group)
async def cmd_skip(client: Client, message: Message):
    try:
        while not play_queue.empty():
            _, _ = play_queue.get_nowait()
            play_queue.task_done()
        await pytg.leave_group_call(GROUP_ID)
        await message.reply_text("Skipped current track.")
    except Exception as e:
        await message.reply_text(f"Skip error: {e}")

# ---------- Main ----------
async def main():
    await app.start()
    await pytg.start()
    logger.info("Bot started! Waiting for messages...")
    await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Exiting...")
