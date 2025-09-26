import os
import asyncio
from dotenv import load_dotenv
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import ChatAdminRequired, PeerIdInvalid
from .utils.logger import logger as _  # init logger
from .utils.ytdl import get_best_audio
from .player import Player

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x]
SUDO_ONLY = os.getenv("SUDO_ONLY", "true").lower() == "true"

if not API_ID or not API_HASH or not BOT_TOKEN or not SESSION_STRING:
    raise SystemExit("Please set API_ID, API_HASH, BOT_TOKEN, SESSION_STRING env vars.")

bot = Client("music-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("music-user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

player = Player(user_client=user)

def is_admin(user_id: int) -> bool:
    return (not SUDO_ONLY) or (user_id in ADMINS)

@bot.on_message(filters.command("start") & filters.private)
async def start_pm(_, m: Message):
    await m.reply_text("🎵 Hi! Add me to a group and make sure the assistant account is in the group too. Use /join and /play.")

@bot.on_message(filters.command("join") & filters.group)
async def join_vc(_, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text("Only admins can do this.")
    try:
        await player.join(m.chat.id)
        await m.reply_text("✅ Ready to play! Start with /play <song or url>")
    except ChatAdminRequired:
        await m.reply_text("I need admin with voice chat permissions.")
    except Exception as e:
        await m.reply_text(f"Join failed: {e}")

@bot.on_message(filters.command("leave") & filters.group)
async def leave_vc(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    await player.leave(m.chat.id)
    await m.reply_text("👋 Left voice chat.")

@bot.on_message(filters.command("play") & filters.group)
async def play_cmd(_, m: Message):
    if SUDO_ONLY and not is_admin(m.from_user.id):
        return await m.reply_text("Only admins can control playback.")
    if len(m.command) < 2:
        return await m.reply_text("Usage: /play <url|query>")
    query = " ".join(m.command[1:])
    msg = await m.reply_text("🔎 Searching...")
    try:
        url, title, duration = get_best_audio(query)
        started = await player.enqueue_and_play(m.chat.id, url, title, duration, m.from_user.id)
        if started:
            await msg.edit_text(f"▶️ Playing: <b>{title}</b>", disable_web_page_preview=True)
        else:
            await msg.edit_text(f"➕ Queued: <b>{title}</b>", disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {e}")

@bot.on_message(filters.command("skip") & filters.group)
async def skip_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    await player.skip(m.chat.id)
    await m.reply_text("⏭️ Skipped.")

@bot.on_message(filters.command("pause") & filters.group)
async def pause_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    await player.pause(m.chat.id)
    await m.reply_text("⏸️ Paused.")

@bot.on_message(filters.command("resume") & filters.group)
async def resume_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    await player.resume(m.chat.id)
    await m.reply_text("▶️ Resumed.")

@bot.on_message(filters.command("stop") & filters.group)
async def stop_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    await player.stop(m.chat.id)
    await m.reply_text("⏹️ Stopped and cleared queue.")

@bot.on_message(filters.command("queue") & filters.group)
async def queue_cmd(_, m: Message):
    q = player.queue.list(m.chat.id)
    if not q:
        return await m.reply_text("(empty)")
    lines = [f"{i+1}. {title} ({duration or 0}s)" for i, (_, _, title, duration) in enumerate(q)]
    await m.reply_text("\n".join(lines))

@bot.on_message(filters.command("volume") & filters.group)
async def volume_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        return
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply_text("Usage: /volume <0-200>")
    vol = int(m.command[1])
    vol = player.set_volume(m.chat.id, vol)
    await m.reply_text(f"🔊 Volume set to {vol}% (applies next track)")

async def main():
    await user.start()
    await player.start()
    await bot.start()
    logger.info("Bot is online")
    await asyncio.get_event_loop().create_future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
