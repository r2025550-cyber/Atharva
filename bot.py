import os
import sys
import json
import asyncio
import logging
import tempfile
import signal
import subprocess
from pathlib import Path
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytgcalls import GroupCallFactory, StreamType
from pytgcalls.types.input_stream import AudioPiped

from gtts import gTTS
import aiohttp
import yt_dlp

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
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "")
DEFAULT_TTS_VOICE = os.getenv("ELEVEN_DEFAULT_VOICE", ELEVEN_VOICE_ID)
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ---------- INIT ----------
app = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
gcf = GroupCallFactory(app)
pytg = gcf.get_group_call()

# temp directory
temp_dir = Path(tempfile.gettempdir()) / "vcbot_cache"
temp_dir.mkdir(parents=True, exist_ok=True)

# concurrency control and queue
AUDIO_SEMAPHORE = asyncio.Semaphore(1)
play_queue: asyncio.Queue = asyncio.Queue()
current_track: Optional[dict] = None
queue_list = []

# Modes
tts_mode = "gtts"
tts_lang = "hi"
dj_mode = False
clean_mode = False

# Playlist system
playlist_file = Path("playlists.json")
playlist_lock = asyncio.Lock()

# Store last now playing message to delete later
last_np_message: Optional[Message] = None


# ---------- HELPERS ----------
async def is_admin(c: Client, user_id: int) -> bool:
    try:
        member = await c.get_chat_member(GROUP_ID, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def auto_delete(msg: Message, delay: int = 30):
    if clean_mode:
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass

def run_ffmpeg_filter(input_path: str, output_path: str, af_filter: str, timeout: int = 30) -> bool:
    cmd = ["ffmpeg", "-y", "-i", input_path, "-af", af_filter, output_path]
    try:
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return completed.returncode == 0
    except Exception:
        return False

def apply_effect(path: str, effect: str) -> Optional[str]:
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
    if run_ffmpeg_filter(path, out, af):
        return out
    return None

def yt_download(query: str):
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
            info = ydl.extract_info(query, download=True)
            title = info.get("title")
            duration = info.get("duration")
            thumb = info.get("thumbnail")
            return outname, title, duration, thumb
    except Exception as e:
        logger.error(f"yt-dlp error: {e}")
        return None, None, None, None

async def tts_gtts(text: str, lang: str = tts_lang) -> Optional[str]:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
        def _save():
            gTTS(text=text, lang=lang).save(path)
        await asyncio.get_event_loop().run_in_executor(None, _save)
        return path
    except Exception as e:
        logger.error(f"gTTS error: {e}")
        return None

async def tts_eleven(text: str, voice_id: str = DEFAULT_TTS_VOICE) -> Optional[str]:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    if not ELEVEN_API_KEY or not voice_id:
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
                    logger.error(f"ElevenLabs error: {await resp.text()}")
    except Exception as e:
        logger.error(f"ElevenLabs exception: {e}")
    return None


# ---------- NOW PLAYING CARD ----------
async def send_now_playing(m: Message, track: dict):
    global last_np_message
    if last_np_message:
        try:
            await last_np_message.delete()
        except Exception:
            pass
    title = track.get("title") or "Unknown"
    duration = track.get("duration")
    requested_by = track.get("requested_by")
    source_type = track.get("source_type", "Unknown")

    caption = f"▶️ **Now Playing:** {title}\n"
    if duration:
        mins, secs = divmod(duration, 60)
        caption += f"⏱ **Duration:** {mins}:{secs:02d}\n"
    if requested_by:
        caption += f"🙋 **Requested by:** {requested_by}\n"
    caption += f"📡 **Source:** {source_type}\n"
    caption += "\n✨ **Powered by VC Bot | Atharva Group** ✨"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏯ Pause/Resume", callback_data="ctrl_pause"),
         InlineKeyboardButton("⏭ Skip", callback_data="ctrl_skip")],
        [InlineKeyboardButton("🎚 Effects", callback_data="effects_menu"),
         InlineKeyboardButton("🗣 Mode", callback_data="mode_menu")]
    ])
    msg = await m.reply(caption, reply_markup=kb)
    last_np_message = msg


# ---------- PLAYBACK ENGINE ----------
async def join_and_play(filepath: str, track: dict, m: Message = None):
    global current_track
    async with AUDIO_SEMAPHORE:
        try:
            await pytg.leave_group_call(GROUP_ID)
        except Exception:
            pass
        await asyncio.sleep(0.5)
        await pytg.join_group_call(
            GROUP_ID,
            AudioPiped(filepath),
            stream_type=StreamType().local_stream
        )
        current_track = track
        if m:
            await send_now_playing(m, track)

async def queue_worker():
    global current_track
    while True:
        item = await play_queue.get()
        try:
            source = item.get("source")
            effect = item.get("effect")
            title = item.get("title")
            duration = item.get("duration")
            thumb = item.get("thumb")
            msg = item.get("msg")
            requested_by = item.get("requested_by")
            source_type = item.get("source_type", "Unknown")

            # Download from YouTube if needed
            path = None
            if isinstance(source, str) and (source.startswith("http") or source.startswith("www")):
                path, yt_title, yt_dur, yt_thumb = await asyncio.get_event_loop().run_in_executor(None, lambda: yt_download(source))
                if yt_title:
                    title, duration, thumb = yt_title, yt_dur, yt_thumb
            else:
                path = source

            if not path:
                continue
            if effect:
                ef_path = apply_effect(path, effect)
                if ef_path:
                    path = ef_path

            track = {
                "path": path,
                "title": title,
                "duration": duration,
                "thumb": thumb,
                "requested_by": requested_by,
                "source_type": source_type
            }
            await join_and_play(path, track, msg)
        finally:
            play_queue.task_done()


# ---------- COMMAND HANDLERS ----------
@app.on_message(filters.command("start"))
async def start_handler(c: Client, m: Message):
    logger.info(f"Got /start from {m.from_user.id} in chat {m.chat.id}")
    await m.reply("✅ Bot is alive and ready!")


@app.on_message(filters.command("help"))
async def help_handler(c: Client, m: Message):
    logger.info(f"Got /help from {m.from_user.id} in chat {m.chat.id}")
    text = (
        "🤖 **VC Bot Commands**\n\n"
        "🎶 Music:\n/play <url/query>\n/skip\n/queue\n\n"
        "🗣 TTS:\n/tts <text>\n/mode\n/language <code>\n\n"
        "🎛 Effects: Bass | Deep | Fast | Echo\n\n"
        "📂 Playlist:\n/playlist add <url>\n/playlist show\n/playlist play\n/playlist clear\n\n"
        "⚙ Admin:\n/djmode on|off\n/cleanmode on|off\n\n"
        "📡 Channel → VC:\nChannel text auto plays in VC.\n\n"
        "✨ Powered by VC Bot | Atharva Group"
    )
    await m.reply(text)


@app.on_message(filters.command("play"))
async def play_handler(c: Client, m: Message):
    logger.info(f"Got /play from {m.from_user.id} in chat {m.chat.id}")
    if len(m.command) < 2:
        return await m.reply("Usage: /play <song name or YouTube link>")
    query = m.text.split(maxsplit=1)[1]
    requested_by = m.from_user.mention if m.from_user else "Unknown"
    await play_queue.put({
        "source": query,
        "effect": None,
        "title": query,
        "duration": None,
        "thumb": None,
        "msg": m,
        "requested_by": requested_by,
        "source_type": "Music"
    })
    await m.reply("🎶 Added to queue!")


@app.on_message(filters.command("skip"))
async def skip_handler(c: Client, m: Message):
    logger.info(f"Got /skip from {m.from_user.id} in chat {m.chat.id}")
    try:
        await pytg.leave_group_call(GROUP_ID)
        await m.reply("⏭ Skipped!")
    except Exception as e:
        await m.reply(f"❌ Skip error: {e}")


@app.on_message(filters.command("tts"))
async def tts_handler(c: Client, m: Message):
    logger.info(f"Got /tts from {m.from_user.id} in chat {m.chat.id}")
    if len(m.command) < 2:
        return await m.reply("Usage: /tts <text>")
    text = m.text.split(maxsplit=1)[1]
    path = await (tts_gtts(text) if tts_mode == "gtts" else tts_eleven(text))
    if path:
        requested_by = m.from_user.mention if m.from_user else "Unknown"
        await play_queue.put({
            "source": path,
            "effect": None,
            "title": "TTS",
            "duration": None,
            "thumb": None,
            "msg": m,
            "requested_by": requested_by,
            "source_type": "TTS"
        })
        await m.reply("🗣 TTS added to queue!")
    else:
        await m.reply("❌ TTS failed")


@app.on_message(filters.command("mode"))
async def mode_handler(c: Client, m: Message):
    logger.info(f"Got /mode from {m.from_user.id} in chat {m.chat.id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙 gTTS", callback_data="tts_gtts"),
         InlineKeyboardButton("🧠 ElevenLabs", callback_data="tts_eleven")]
    ])
    await m.reply("Select TTS mode:", reply_markup=keyboard)


@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def channel_handler(c: Client, m: Message):
    logger.info(f"Got channel text in {m.chat.id}")
    path = await (tts_gtts(m.text) if tts_mode == "gtts" else tts_eleven(m.text))
    if path:
        await play_queue.put({
            "source": path,
            "effect": None,
            "title": "Channel Message",
            "duration": None,
            "thumb": None,
            "msg": m,
            "requested_by": f"Channel {m.chat.title}",
            "source_type": "Channel Text"
        })


@app.on_callback_query()
async def cb_handler(c: Client, q: CallbackQuery):
    global tts_mode
    logger.info(f"Callback data: {q.data} from {q.from_user.id}")
    if q.data == "tts_gtts":
        tts_mode = "gtts"
        await q.answer("✅ gTTS mode enabled")
    elif q.data == "tts_eleven":
        tts_mode = "eleven"
        await q.answer("✅ ElevenLabs mode enabled")
    elif q.data.startswith("fx_"):
        effect = q.data.split("_")[1]
        if current_track:
            ef_path = apply_effect(current_track["path"], effect)
            if ef_path:
                await join_and_play(ef_path, current_track, q.message)


# ---------- START ----------
async def start_bot():
    await app.start()
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

def _signal_handler(sig, frame):
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
        sys.exit(1)
