#!/usr/bin/env python3
# bot.py — Final merged music + TTS VC bot
# Features: YouTube/music playback, voice notes, TTS (gTTS/ElevenLabs),
# per-chat queues, per-user playlists, basic voice effects, admin/owner controls,
# channel->VC TTS, help/buttons, clean mode, DJ mode, branding footer.

import os
import re
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType
from pytgcalls import PyTgCalls, idle
from pytgcalls.types import Update
from pytgcalls.types.input_stream import InputStream
from pytgcalls.types.input_stream.fft import AudioPiped

from yt_dlp import YoutubeDL
from gtts import gTTS
import aiohttp
import uuid
import shlex
import subprocess

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("vcbot")

# ---------------- Env / Config ----------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")  # assistant (user) session string
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SUDO_USERS = {int(x) for x in os.getenv("SUDO_USERS", "").split(",") if x.strip().isdigit()}
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0") or 0)
GROUP_ID = int(os.getenv("GROUP_ID", "0") or 0)   # where VC is
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "")
CLEAN_MODE_ENV = os.getenv("CLEAN_MODE", "0")

BRANDING = "Powered by VC Bot | Atharva Group"

# ---------------- Clients ----------------
# BOT for command interface; USER (assistant) for joining VCs via pytgcalls
bot = Client("vc_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
user = Client("vc_user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)
calls = PyTgCalls(user)

# ---------------- Globals / State ----------------
TMP = Path(tempfile.gettempdir()) / "vcbot"
TMP.mkdir(parents=True, exist_ok=True)

YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "default_search": "ytsearch",
    "nocheckcertificate": True,
    "cachedir": False,
}

queues: Dict[int, List[dict]] = {}    # chat_id -> queue of tracks
now_playing: Dict[int, Optional[dict]] = {}  # chat_id -> track
autoplay_on: Dict[int, bool] = {}     # chat_id -> bool
per_user_playlists: Dict[int, List[dict]] = {}   # user_id -> list of tracks

tts_mode = "gtts"   # or "eleven"
tts_lang = "hi"

# DJ/Clean modes
dj_mode = False
clean_mode = CLEAN_MODE_ENV == "1"

# Supported voice effects (converted into ffmpeg filter chains)
EFFECTS = {
    "none": None,
    "fast": "atempo=1.5",
    "slow": "atempo=0.8",
    "deep": "asetrate=44100*0.8,aresample=44100",
    "chipmunk": "asetrate=44100*1.5,aresample=44100",
}

# ---------------- Helpers ----------------
def is_admin_or_owner(m: Message) -> bool:
    uid = m.from_user.id if m.from_user else 0
    if uid == OWNER_ID or uid in SUDO_USERS:
        return True
    try:
        # fallback: check chat admin (if in group)
        # Note: we don't make network calls here; trust owner/sudo mainly.
        return False
    except Exception:
        return False

def extract_query(text: str) -> Optional[str]:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None

def is_url(s: str) -> bool:
    return bool(re.match(r"https?://", s))

def yt_search_extract(query: str) -> Tuple[str, str, str]:
    """Return (title, stream_url, webpage_url) — may raise"""
    with YoutubeDL(YTDL_OPTS) as ydl:
        if is_url(query):
            info = ydl.extract_info(query, download=False)
        else:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
        # choose best audio url
        if "url" in info:
            stream_url = info["url"]
        else:
            formats = info.get("formats", [])
            aformats = [f for f in formats if f.get("acodec") and (not f.get("vcodec") or f.get("vcodec") in (None, "none"))]
            aformats.sort(key=lambda f: f.get("abr", 0), reverse=True)
            stream_url = aformats[0]["url"] if aformats else formats[-1]["url"]
        title = info.get("title", "Unknown")
        webpage = info.get("webpage_url", info.get("original_url", ""))
        return title, stream_url, webpage

async def tts_gtts(text: str, lang: str = "hi") -> Optional[str]:
    fname = str(TMP / f"tts_{uuid.uuid4().hex}.mp3")
    try:
        gTTS(text=text, lang=lang).save(fname)
        return fname
    except Exception as e:
        logger.exception("gTTS error: %s", e)
        return None

async def tts_eleven(text: str) -> Optional[str]:
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        logger.warning("ElevenLabs credentials missing")
        return None
    fname = str(TMP / f"tts_eleven_{uuid.uuid4().hex}.mp3")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {"text": text, "model_id": "eleven_monolingual_v1"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(fname, "wb") as f:
                        f.write(data)
                    return fname
                else:
                    logger.error("ElevenLabs API error: %s", await resp.text())
                    return None
    except Exception as e:
        logger.exception("ElevenLabs request failed: %s", e)
        return None

def apply_effect(input_path: str, effect_name: str) -> str:
    """Apply a simple ffmpeg filter to create a new file with effect.
    Returns new file path. If effect is 'none' or unknown, returns original."""
    if not effect_name or effect_name == "none":
        return input_path
    filt = EFFECTS.get(effect_name)
    if not filt:
        return input_path
    out = str(TMP / f"eff_{effect_name}_{uuid.uuid4().hex}.mp3")
    # Build ffmpeg command
    # -y overwrite, -i input, -af filter, -vn, -f mp3 output
    cmd = ["ffmpeg", "-y", "-i", input_path, "-af", filt, "-vn", "-f", "mp3", out]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out
    except Exception as e:
        logger.exception("Effect ffmpeg failed: %s", e)
        return input_path

async def start_stream(chat_id: int, track: dict):
    now_playing[chat_id] = track
    logger.info("Starting stream in chat %s -> %s", chat_id, track.get("title"))
    try:
        # If stream_url is a local file path, use it; else, stream URL directly
        src = track.get("stream_url")
        await calls.join_group_call(chat_id, InputStream(AudioPiped(src)))
    except Exception as e:
        logger.warning("join_group_call failed, attempting change_stream: %s", e)
        try:
            await calls.change_stream(chat_id, InputStream(AudioPiped(track.get("stream_url"))))
        except Exception as e2:
            logger.exception("change_stream also failed: %s", e2)

def add_to_queue(chat_id: int, track: dict):
    queues.setdefault(chat_id, []).append(track)

def pop_next(chat_id: int) -> Optional[dict]:
    q = queues.get(chat_id, [])
    return q.pop(0) if q else None

async def safe_delete(msg: Message, delay: int = 5):
    if not msg:
        return
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass

# ---------------- Commands ----------------
@bot.on_message(filters.command(["start", "help"]) & (filters.private | filters.group))
async def cmd_help(c: Client, m: Message):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎙 Switch TTS", callback_data="btn_mode")],
            [InlineKeyboardButton("⚙️ DJ Mode", callback_data="btn_dj")],
            [InlineKeyboardButton("🧹 Clean Mode", callback_data="btn_clean")],
        ]
    )
    text = (
        f"🎧 **VC Bot**\n\n"
        f"Commands (Group only):\n"
        f"/play <song or url>\n/skip\n/stop\n/pause\n/resume\n/queue\n/tts <text>\n/mode (TTS mode)\n"
        f"/djmode on|off\n/cleanmode on|off\n/playlist add/list/remove\n\n"
        f"{BRANDING}"
    )
    await m.reply_text(text, reply_markup=keyboard)

@bot.on_message(filters.command("mode") & filters.group)
async def cmd_mode(c: Client, m: Message):
    global tts_mode
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎙 gTTS", callback_data="set_tts_gtts"),
             InlineKeyboardButton("🧠 ElevenLabs", callback_data="set_tts_eleven")]
        ]
    )
    await m.reply_text(f"Current TTS mode: {tts_mode}\nChoose:", reply_markup=kb)

@bot.on_callback_query()
async def cb_handler(c: Client, q: CallbackQuery):
    global tts_mode, dj_mode, clean_mode
    data = q.data or ""
    if data == "set_tts_gtts":
        tts_mode = "gtts"
        await q.answer("gTTS selected")
    elif data == "set_tts_eleven":
        tts_mode = "eleven"
        await q.answer("ElevenLabs selected")
    elif data == "btn_dj":
        dj_mode = not dj_mode
        await q.answer(f"DJ Mode {'enabled' if dj_mode else 'disabled'}")
    elif data == "btn_clean":
        clean_mode = not clean_mode
        await q.answer(f"Clean Mode {'enabled' if clean_mode else 'disabled'}")
    elif data == "btn_mode":
        await cmd_mode(c, q.message)
    else:
        await q.answer()

@bot.on_message(filters.command("play") & filters.group)
async def cmd_play(c: Client, m: Message):
    if dj_mode and not is_admin_or_owner(m):
        return await m.reply_text("❌ DJ Mode active — only DJs can queue/play.")
    q = extract_query(m.text or "")
    # if user replied to audio or voice note, accept that too
    if not q and m.reply_to_message:
        if m.reply_to_message.audio or m.reply_to_message.voice or m.reply_to_message.document:
            # download replied file and play locally
            msg = await m.reply_text("⬇️ Downloading file...")
            file_path = await m.reply_to_message.download(file_name=str(TMP))
            title = m.reply_to_message.audio.title if m.reply_to_message.audio else "Voice/Audio"
            track = {"title": title, "stream_url": file_path, "webpage": ""}
            if now_playing.get(m.chat.id):
                add_to_queue(m.chat.id, track)
                await msg.edit_text(f"➕ Queued: {title}")
            else:
                await msg.edit_text("▶️ Playing...")
                await start_stream(m.chat.id, track)
            if clean_mode:
                asyncio.create_task(safe_delete(m, 5))
            return

    if not q:
        await m.reply_text("Usage: /play <song name or YouTube URL> (or reply to an audio/voice)")
        return
    msg = await m.reply_text("🔎 Preparing…")
    try:
        title, stream_url, webpage = await asyncio.get_event_loop().run_in_executor(None, yt_search_extract, q)
        track = {"title": title, "stream_url": stream_url, "webpage": webpage, "requested_by": m.from_user.mention if m.from_user else "user", "effect": "none"}
        if now_playing.get(m.chat.id):
            add_to_queue(m.chat.id, track)
            await msg.edit_text(f"➕ Queued: {title}")
        else:
            await msg.edit_text(f"▶️ Now playing: {title}")
            await start_stream(m.chat.id, track)
    except Exception as e:
        logger.exception("play error: %s", e)
        await msg.edit_text(f"❌ Error: {e}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("skip") & filters.group)
async def cmd_skip(c: Client, m: Message):
    if not is_admin_or_owner(m):
        return await m.reply_text("Only owner/admins can skip.")
    nxt = pop_next(m.chat.id)
    if nxt:
        await start_stream(m.chat.id, nxt)
        await m.reply_text(f"⏭️ Now: {nxt['title']}")
    else:
        try:
            await calls.leave_group_call(m.chat.id)
        except Exception:
            pass
        now_playing[m.chat.id] = None
        await m.reply_text("⏹ Queue empty. Left VC.")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("stop") & filters.group)
async def cmd_stop(c: Client, m: Message):
    if not is_admin_or_owner(m):
        return await m.reply_text("Only owner/admins can stop.")
    queues[m.chat.id] = []
    now_playing[m.chat.id] = None
    try:
        await calls.leave_group_call(m.chat.id)
    except Exception:
        pass
    await m.reply_text("🛑 Stopped & cleared queue.")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("pause") & filters.group)
async def cmd_pause(c: Client, m: Message):
    if not is_admin_or_owner(m): return await m.reply_text("Only owner/admins can pause.")
    try:
        await calls.pause_stream(m.chat.id)
        await m.reply_text("⏸️ Paused.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("resume") & filters.group)
async def cmd_resume(c: Client, m: Message):
    if not is_admin_or_owner(m): return await m.reply_text("Only owner/admins can resume.")
    try:
        await calls.resume_stream(m.chat.id)
        await m.reply_text("▶️ Resumed.")
    except Exception as e:
        await m.reply_text(f"❌ {e}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("queue") & filters.group)
async def cmd_queue(c: Client, m: Message):
    q = queues.get(m.chat.id, [])
    if not q:
        return await m.reply_text("📭 Queue is empty.")
    txt = "🗒️ Queue:\n" + "\n".join([f"{i+1}. {t['title']} — {t.get('requested_by','user')}" for i, t in enumerate(q[:20])])
    await m.reply_text(txt)
    if clean_mode:
        asyncio.create_task(safe_delete(m, 10))

@bot.on_message(filters.command("autoplay") & filters.group)
async def cmd_autoplay(c: Client, m: Message):
    if not is_admin_or_owner(m): return await m.reply_text("Only owner/admins can toggle autoplay.")
    args = extract_query(m.text or "")
    if not args or args.lower() not in ("on", "off"):
        return await m.reply_text("Usage: /autoplay on|off")
    autoplay_on[m.chat.id] = (args.lower() == "on")
    await m.reply_text(f"♾️ Autoplay set to {args.upper()}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("tts") & (filters.group | filters.channel))
async def cmd_tts(c: Client, m: Message):
    # If in channel and channel==CHANNEL_ID, forward to GROUP_ID
    text = extract_query(m.text or "")
    if not text:
        # if replied message has text/caption
        if m.reply_to_message and (m.reply_to_message.text or m.reply_to_message.caption):
            text = m.reply_to_message.text or m.reply_to_message.caption
        else:
            return await m.reply_text("Usage: /tts <text>")

    msg = await m.reply_text("🎤 Generating TTS...")
    if tts_mode == "gtts":
        path = await tts_gtts(text, tts_lang)
    else:
        path = await tts_eleven(text)
    if not path:
        return await msg.edit_text("❌ TTS failed")
    # if message originated in channel and CHANNEL_ID configured, play to GROUP_ID
    target_chat = m.chat.id
    if m.chat.type == ChatType.CHANNEL and CHANNEL_ID and GROUP_ID:
        target_chat = GROUP_ID
    track = {"title": f"TTS by {m.from_user.first_name if m.from_user else 'user'}", "stream_url": path, "webpage": ""}
    if now_playing.get(target_chat):
        add_to_queue(target_chat, track)
        await msg.edit_text("➕ TTS queued")
    else:
        await msg.edit_text("🔊 TTS playing")
        await start_stream(target_chat, track)
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("djmode") & filters.group)
async def cmd_djmode(c: Client, m: Message):
    global dj_mode
    if not is_admin_or_owner(m): return await m.reply_text("Only owner/admins can toggle.")
    arg = extract_query(m.text or "")
    if not arg or arg.lower() not in ("on", "off"):
        return await m.reply_text("Usage: /djmode on|off")
    dj_mode = (arg.lower() == "on")
    await m.reply_text(f"DJ Mode {'enabled' if dj_mode else 'disabled'}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("cleanmode") & filters.group)
async def cmd_cleanmode(c: Client, m: Message):
    global clean_mode
    if not is_admin_or_owner(m): return await m.reply_text("Only owner/admins can toggle.")
    arg = extract_query(m.text or "")
    if not arg or arg.lower() not in ("on", "off"):
        return await m.reply_text("Usage: /cleanmode on|off")
    clean_mode = (arg.lower() == "on")
    await m.reply_text(f"Clean Mode {'enabled' if clean_mode else 'disabled'}")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 5))

@bot.on_message(filters.command("playlist") & filters.group)
async def cmd_playlist(c: Client, m: Message):
    # /playlist add <query>
    # /playlist list
    # /playlist remove <index>
    sub = extract_query(m.text or "") or ""
    parts = sub.split(maxsplit=1)
    action = parts[0].lower() if parts else ""
    user_id = m.from_user.id if m.from_user else 0
    if action == "add" and len(parts) > 1:
        q = parts[1]
        msg = await m.reply_text("🔎 Preparing playlist item...")
        try:
            title, stream_url, webpage = await asyncio.get_event_loop().run_in_executor(None, yt_search_extract, q)
            per_user_playlists.setdefault(user_id, []).append({"title": title, "stream_url": stream_url, "webpage": webpage})
            await msg.edit_text(f"➕ Added to your playlist: {title}")
        except Exception as e:
            await msg.edit_text(f"❌ {e}")
    elif action == "list":
        pl = per_user_playlists.get(user_id, [])
        if not pl:
            await m.reply_text("No playlist items.")
        else:
            txt = "\n".join([f"{i+1}. {t['title']}" for i, t in enumerate(pl)])
            await m.reply_text("🎶 Your playlist:\n" + txt)
    elif action == "remove" and len(parts) > 1:
        try:
            idx = int(parts[1]) - 1
            pl = per_user_playlists.get(user_id, [])
            if 0 <= idx < len(pl):
                item = pl.pop(idx)
                await m.reply_text(f"Removed: {item['title']}")
            else:
                await m.reply_text("Invalid index")
        except Exception:
            await m.reply_text("Usage: /playlist remove <index>")
    else:
        await m.reply_text("Usage:\n/playlist add <song>\n/playlist list\n/playlist remove <index>")
    if clean_mode:
        asyncio.create_task(safe_delete(m, 10))

# ---------------- PyTgCalls update handler (auto-next) ----------------
@calls.on_update()
async def on_calls_update(_, update: Update):
    try:
        if getattr(update, "audio_ended", False):
            chat_id = update.chat_id
            logger.info("Audio ended in %s", chat_id)
            nxt = pop_next(chat_id)
            if nxt:
                await start_stream(chat_id, nxt)
                try:
                    await bot.send_message(chat_id, f"▶️ Now playing: {nxt.get('title')}")
                except Exception:
                    pass
            else:
                now_playing[chat_id] = None
                try:
                    await calls.leave_group_call(chat_id)
                except Exception:
                    pass
    except Exception:
        logger.exception("Error in on_calls_update")

# ---------------- Channel -> group TTS: watch channel messages ----------------
@bot.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def channel_to_vc(c: Client, m: Message):
    # If channel id configured and we get text, turn into TTS and play in GROUP_ID
    if not CHANNEL_ID or not GROUP_ID:
        return
    text = m.text or m.caption or ""
    if not text:
        return
    try:
        logger.info("Channel message captured for TTS -> playing to group %s", GROUP_ID)
        path = await tts_gtts(text, tts_lang) if tts_mode == "gtts" else await tts_eleven(text)
        if not path:
            return
        track = {"title": "Channel TTS", "stream_url": path, "webpage": ""}
        if now_playing.get(GROUP_ID):
            add_to_queue(GROUP_ID, track)
        else:
            await start_stream(GROUP_ID, track)
    except Exception:
        logger.exception("channel_to_vc failed")

# ---------------- Startup / Main ----------------
async def _start_all():
    await bot.start()
    await user.start()
    await calls.start()
    logger.info("Bot + user + calls started. Ready.")
    # ensure GROUP_ID existing / no-op if not set
    if GROUP_ID:
        logger.info("Configured GROUP_ID: %s", GROUP_ID)
    logger.info(BRANDING)
    await idle()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(_start_all())
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        try:
            asyncio.get_event_loop().run_until_complete(calls.stop())
        except Exception:
            pass
        try:
            asyncio.get_event_loop().run_until_complete(user.stop())
        except Exception:
            pass
        try:
            asyncio.get_event_loop().run_until_complete(bot.stop())
        except Exception:
            pass
