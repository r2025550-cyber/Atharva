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
from pytgcalls import GroupCallFactory

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

# ---------- PLAYLIST HELPERS ----------
async def load_playlists():
    if not playlist_file.exists():
        return {}
    try:
        with open(playlist_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

async def save_playlists(data: dict):
    async with playlist_lock:
        with open(playlist_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

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
    except Exception:
        return None, None, None, None

async def tts_gtts(text: str, lang: str = tts_lang) -> Optional[str]:
    path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=temp_dir).name
    try:
        def _save():
            gTTS(text=text, lang=lang).save(path)
        await asyncio.get_event_loop().run_in_executor(None, _save)
        return path
    except Exception:
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
    except Exception:
        return None
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
    thumb = track.get("thumb")
    requested_by = track.get("requested_by")
    source_type = track.get("source_type", "Unknown")

    caption = f"▶️ **Now Playing:** {title}\n"
    if duration:
        mins, secs = divmod(duration, 60)
        caption += f"⏱ **Duration:** {mins}:{secs:02d}\n"
    if requested_by:
        caption += f"🙋 **Requested by:** {requested_by}\n"
    caption += f"📡 **Source:** {source_type}\n"
    caption += "\n✨ **Powered by [VC Bot | Atharva Group]** ✨"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏯ Pause/Resume", callback_data="ctrl_pause"),
         InlineKeyboardButton("⏭ Skip", callback_data="ctrl_skip")],
        [InlineKeyboardButton("🎚 Effects", callback_data="effects_menu"),
         InlineKeyboardButton("🗣 Mode", callback_data="mode_menu")]
    ])
    if thumb:
        msg = await m.reply_photo(thumb, caption=caption, reply_markup=kb)
    else:
        msg = await m.reply(caption, reply_markup=kb)
    last_np_message = msg

# ---------- COMMANDS ----------
@app.on_message(filters.command("help") & filters.group)
async def help_handler(c: Client, m: Message):
    text = (
        "🤖 **VC Bot Commands**\n\n"
        "🎶 Music:\n"
        "  /play <url/query> - Play from YouTube/Reply file\n"
        "  /skip - Skip current\n"
        "  /queue - Show queue\n\n"
        "🗣 TTS:\n"
        "  /tts <text> - Convert text to voice\n"
        "  /mode - Switch TTS mode (gTTS/ElevenLabs)\n"
        "  /language <code> - Change TTS language\n\n"
        "🎛 Effects:\n"
        "  Bass | Deep | Fast | Echo (via buttons)\n\n"
        "📂 Playlist:\n"
        "  /playlist add <url/query>\n"
        "  /playlist show | play | clear\n\n"
        "⚙ Admin:\n"
        "  /djmode on|off - Restrict playback to admins\n"
        "  /cleanmode on|off - Auto-delete replies\n\n"
        "📡 Channel → VC:\n"
        "  Post text in channel, it will auto play in group VC.\n\n"
        "✨ Powered by VC Bot | Atharva Group"
    )
    await m.reply(text)

@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def channel_broadcast(c: Client, m: Message):
    text = m.text.strip()
    if not text:
        return
    path = await (tts_gtts(text, tts_lang) if tts_mode == "gtts" else tts_eleven(text))
    if path:
        requested_by = f"Channel: {m.chat.title}"
        await play_queue.put({
            "source": path, "effect": None, "title": "Channel Broadcast",
            "duration": None, "thumb": None, "msg": m,
            "requested_by": requested_by, "source_type": "Channel Text"
        })

# ---------- CALLBACK HANDLERS ----------
@app.on_callback_query()
async def cb_handler(c: Client, q: CallbackQuery):
    global tts_mode
    if q.data == "mode_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 gTTS", callback_data="tts_gtts"),
             InlineKeyboardButton("🧠 ElevenLabs", callback_data="tts_eleven")]
        ])
        await q.message.reply("Select TTS mode:", reply_markup=kb)
    elif q.data == "tts_gtts":
        tts_mode = "gtts"
        await q.answer("✅ gTTS mode enabled")
    elif q.data == "tts_eleven":
        tts_mode = "eleven"
        await q.answer("✅ ElevenLabs mode enabled")
    elif q.data == "effects_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Bass", callback_data="fx_bass"),
             InlineKeyboardButton("🕳 Deep", callback_data="fx_deep")],
            [InlineKeyboardButton("⚡ Fast", callback_data="fx_fast"),
             InlineKeyboardButton("🎶 Echo", callback_data="fx_echo")]
        ])
        await q.message.reply("Select effect:", reply_markup=kb)
    await q.answer()

# ---------- START ----------
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
