import asyncio
import os
from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from dotenv import load_dotenv

from .player import Player
from .utils.ytdlp_helper import ytdlp_search_best
from .queue import MusicQueue

load_dotenv()

API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")

ADMINS = {int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x.isdigit()}
SUDO_ONLY = os.getenv("SUDO_ONLY", "true").lower() == "true"
GROUP_ID = os.getenv("GROUP_ID")  # optional
CHANNEL_ID = os.getenv("CHANNEL_ID")  # optional

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=LOG_LEVEL)

if not (API_ID and API_HASH and BOT_TOKEN and SESSION_STRING):
    raise SystemExit("Missing required env vars: API_ID, API_HASH, BOT_TOKEN, SESSION_STRING")

bot = Client("music-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
user = Client("music-user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)

player = Player(user)
queue = MusicQueue()

def is_admin(user_id: int) -> bool:
    return (user_id in ADMINS) or (not SUDO_ONLY)

def allowed_chat(chat_id: int) -> bool:
    if GROUP_ID and GROUP_ID.strip():
        try:
            return int(GROUP_ID) == chat_id
        except:
            return True
    return True

@bot.on_message(filters.command(["start", "help"]))
async def start_cmd(_, m):
    await m.reply_text(
        "🎧 **Advanced Music Bot (TgCaller)**\n\n"
        "Commands:\n"
        "/join – join voice chat\n"
        "/leave – leave voice chat\n"
        "/play <query|url> – play/queue\n"
        "/skip – next track\n"
        "/pause, /resume, /stop\n"
        "/queue – show queue\n"
        "/volume 0-200\n"
        "/np – now playing\n"
        f"Admin-only: {SUDO_ONLY}\n"
    )

@bot.on_message(filters.command("join"))
async def join_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await m.reply_chat_action("typing")
    try:
        await player.join(m.chat.id)
        await m.reply_text("✅ Joined voice chat.")
    except Exception as e:
        logger.exception(e)
        await m.reply_text(f"❌ Failed to join: `{e}`")

@bot.on_message(filters.command("leave"))
async def leave_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await m.reply_chat_action("typing")
    try:
        await player.leave(m.chat.id)
        await m.reply_text("👋 Left voice chat.")
    except Exception as e:
        logger.exception(e)
        await m.reply_text(f"❌ Failed to leave: `{e}`")

@bot.on_message(filters.command("play"))
async def play_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    if m.chat.type not in (ChatType.SUPERGROUP, ChatType.GROUP):
        return await m.reply_text("Use in a group with an active voice chat.")
    if len(m.command) < 2 and not (m.reply_to_message and m.reply_to_message.text):
        return await m.reply_text("Usage: /play <url|song name>")
    query = m.text.split(None, 1)[1] if len(m.command) > 1 else m.reply_to_message.text
    await m.reply_chat_action("typing")
    try:
        info = await ytdlp_search_best(query)
        added = await player.enqueue_and_maybe_start(
            chat_id=m.chat.id,
            stream_url=info["url"],
            title=info["title"],
            duration=info.get("duration", 0),
            requested_by=m.from_user.id,
        )
        if added:
            await m.reply_text(f"▶️ **Playing:** {info['title']}")
        else:
            await m.reply_text(f"➕ **Queued:** {info['title']}")
    except Exception as e:
        logger.exception(e)
        await m.reply_text(f"❌ Error: `{e}`")

@bot.on_message(filters.command("skip"))
async def skip_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await player.skip(m.chat.id)
    await m.reply_text("⏭️ Skipped.")

@bot.on_message(filters.command("stop"))
async def stop_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await player.stop(m.chat.id)
    await m.reply_text("⏹️ Stopped and cleared queue.")

@bot.on_message(filters.command("pause"))
async def pause_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await player.pause(m.chat.id)
    await m.reply_text("⏸️ Paused.")

@bot.on_message(filters.command("resume"))
async def resume_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    await player.resume(m.chat.id)
    await m.reply_text("▶️ Resumed.")

@bot.on_message(filters.command("volume"))
async def volume_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    if not is_admin(m.from_user.id): return
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply_text("Usage: /volume <0-200>")
    vol = int(m.command[1])
    v = player.set_volume(m.chat.id, vol)
    try:
        await player.apply_volume(m.chat.id)
    except Exception as e:
        logger.debug(f"Volume apply deferred: {e}")
    await m.reply_text(f"🔊 Volume set to **{v}%**")

@bot.on_message(filters.command("queue"))
async def queue_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    items = player.queue.list(m.chat.id)
    if not items:
        return await m.reply_text("🧾 Queue is empty.")
    lines = []
    for i, item in enumerate(items, 1):
        _, _, title, duration = item
        d = f"{duration//60}:{duration%60:02d}" if duration else "—"
        lines.append(f"{i}. {title} ({d})")
    await m.reply_text("**Queue:**\n" + "\n".join(lines))

@bot.on_message(filters.command(["np", "nowplaying"]))
async def np_cmd(_, m):
    if not allowed_chat(m.chat.id): return
    cur = player.current.get(m.chat.id)
    if not cur: return await m.reply_text("Nothing is playing.")
    _, _, title, duration = cur
    d = f"{duration//60}:{duration%60:02d}" if duration else "—"
    await m.reply_text(f"🎵 **Now Playing:** {title} ({d})")

async def main():
    await bot.start()
    await user.start()
    await player.start()
    logger.info("Bot is up.")
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
