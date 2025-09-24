import os
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import GroupCallFactory
from gtts import gTTS
import yt_dlp
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vcbot")

# ---------- ENV ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # numeric like -100...
GROUP_ID = os.getenv("GROUP_ID", "")      # numeric like -100...

# ---------- Init clients ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
group_call = GroupCallFactory(app).get_group_call()

# ---------- Playback queue ----------
play_queue = asyncio.Queue()
playing_lock = asyncio.Lock()  # ensure single player
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------
async def download_file_from_message(msg: Message) -> Optional[str]:
    """
    If message has audio/document (mp3/ogg/m4a) download and return filepath.
    """
    if msg.audio or msg.document or msg.voice:
        # prefer audio -> document -> voice
        media = msg.audio or msg.document or msg.voice
        fname = f"{temp_dir}/{media.file_id}_{media.file_name or 'audio'}.mp3"
        try:
            logger.info("Downloading media from channel...")
            await msg.download(file_name=fname)
            return fname
        except Exception as e:
            logger.error("Download failed: %s", e)
    return None

def yt_download_to_file(query: str) -> Optional[str]:
    """
    Download best audio from YouTube (or URL) to a local mp3 file via yt-dlp.
    Synchronous because yt-dlp is blocking; we'll call it in executor.
    """
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
        # cleanup
        if os.path.exists(outname):
            try: os.remove(outname)
            except: pass
        return None

async def tts_to_file(text: str, lang: str = "hi") -> Optional[str]:
    """Generate TTS MP3 and return file path"""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(temp_dir))
    tmp.close()
    try:
        tts = gTTS(text=text, lang=lang)
        tts.save(tmp.name)
        return tmp.name
    except Exception as e:
        logger.error("gTTS error: %s", e)
        try: os.remove(tmp.name)
        except: pass
        return None

async def enqueue_and_maybe_play(filepath: str, title: str = None):
    """Put file in queue and ensure playback coroutine running."""
    await play_queue.put((filepath, title or filepath))
    # trigger player if not already running
    if not playing_lock.locked():
        # start player in background
        asyncio.create_task(player_worker())

async def player_worker():
    """
    Worker: pulls from queue and plays sequentially in group call.
    Uses group_call.join and group_call.start_audio(file).
    """
    async with playing_lock:
        while not play_queue.empty():
            filepath, title = await play_queue.get()
            logger.info("Now playing: %s", title)
            try:
                if not group_call.is_connected:
                    await group_call.join(int(GROUP_ID))
                # start audio - uses file path
                await group_call.start_audio(filepath)
                # wait until playback finished; simple approach: poll file lock / duration
                # Here we do a naive wait: check file size stops changing for a moment OR sleep by duration using ffmpeg to get duration.
                # Simpler: wait while group_call.is_playing may not exist; we use a fixed heuristic wait by querying duration via ffmpeg-python
                import ffmpeg
                try:
                    probe = ffmpeg.probe(filepath)
                    duration = float(probe['format']['duration'])
                except Exception:
                    duration = 0
                # minimum wait to allow stream start
                wait_time = max(1.5, duration)
                await asyncio.sleep(wait_time)
                # stop audio (if API provides method, else rely on start_audio finishing)
                try:
                    await group_call.stop_audio()
                except Exception:
                    # some pytgcalls versions auto-stop
                    pass
            except Exception as e:
                logger.error("Playback error: %s", e)
            finally:
                # cleanup local file
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
                play_queue.task_done()
        # optionally leave call after idle
        try:
            if group_call.is_connected:
                await group_call.leave()
        except Exception:
            pass

# ---------- Pyrogram handlers ----------

# 1) Channel text -> TTS
@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def on_channel_text(client: Client, message: Message):
    text = message.text.strip()
    if not text:
        return
    logger.info("Channel text received for TTS")
    mp3 = await tts_to_file(text, lang="hi")
    if mp3:
        await enqueue_and_maybe_play(mp3, title=f"TTS: {text[:30]}")

# 2) Channel MP3 / audio -> download & play
@app.on_message(filters.chat(CHANNEL_ID) & (filters.audio | filters.voice | filters.document))
async def on_channel_media(client: Client, message: Message):
    # check file extension if document
    logger.info("Channel media received")
    path = await download_file_from_message(message)
    if path:
        await enqueue_and_maybe_play(path, title="ChannelAudio")

# 3) Commands in group or channel: /play <url or search>
# We'll accept commands from channel OR group admins (simple policy)
@app.on_message(filters.command("play") & (filters.chat(CHANNEL_ID) | filters.group))
async def cmd_play(client: Client, message: Message):
    # message.text like "/play <query>"
    if len(message.command) < 2:
        await message.reply_text("Usage: /play <YouTube URL or search term or direct link>")
        return
    query = " ".join(message.command[1:])
    await message.reply_text(f"Searching/Downloading: {query}")
    # if query looks like url, pass directly; else use ytsearch:query
    if query.startswith("http://") or query.startswith("https://"):
        target = query
    else:
        target = f"ytsearch:{query}"
    loop = asyncio.get_event_loop()
    # run blocking yt-dlp in executor
    mp3_path = await loop.run_in_executor(None, yt_download_to_file, target)
    if mp3_path:
        await message.reply_text("Queued for play ✅")
        await enqueue_and_maybe_play(mp3_path, title=query)
    else:
        await message.reply_text("Download failed ❌")

# 4) Optional: /skip command
@app.on_message(filters.command("skip") & filters.group)
async def cmd_skip(client: Client, message: Message):
    # kills current playback: we implement by clearing queue and stopping audio
    try:
        while not play_queue.empty():
            _, _ = play_queue.get_nowait()
            play_queue.task_done()
    except asyncio.QueueEmpty:
        pass
    try:
        await group_call.stop_audio()
        await message.reply_text("Skipped current track.")
    except Exception as e:
        await message.reply_text(f"Skip error: {e}")

# ---------- Main ----------
async def main():
    await app.start()
    logger.info("Bot started! Waiting for channel or commands...")
    # No need to start group_call explicitly; join when playing
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Exiting...")
