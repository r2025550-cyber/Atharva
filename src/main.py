import asyncio
import os
from loguru import logger
from pyrogram import Client, filters, idle
from dotenv import load_dotenv
import yt_dlp
import traceback

from .player import Player

# Load env variables
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Clients
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Player
player = Player(user)

# ─── YT-DLP Helper ───────────────────────────────────────────────
async def yt_search(query: str):
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "extract_flat": False,
    }
    loop = asyncio.get_event_loop()
    try:
        def run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return {
                    "url": info["url"],
                    "title": info.get("title", "Unknown Title"),
                    "duration": info.get("duration", 0),
                }
        return await loop.run_in_executor(None, run)
    except Exception as e:
        logger.error(f"yt-dlp error: {e}")
        traceback.print_exc()
        return None

# ─── Debug logger for all messages ───────────────────────────────
@bot.on_message()
async def debug_all(_, msg):
    try:
        logger.debug(f"BOT RECEIVED: chat={msg.chat.id}, user={msg.from_user.id if msg.from_user else 'N/A'}, text={msg.text}")
    except Exception as e:
        logger.error(f"Debug handler error: {e}")

# ─── Handlers ───────────────────────────────────────────────
@bot.on_message(filters.command("start"))
async def start_cmd(_, msg):
    try:
        await msg.reply_text("🤖 Bot is alive and ready!")
        logger.info(f"/start used in chat {msg.chat.id} by {msg.from_user.id}")
    except Exception as e:
        logger.error(f"Error in /start: {e}")
        traceback.print_exc()

@bot.on_message(filters.command("play") & filters.group)
async def play_cmd(_, msg):
    try:
        if len(msg.command) < 2:
            return await msg.reply_text("Usage: `/play <song>`")
        query = " ".join(msg.command[1:])
        await msg.reply_text(f"🎶 Searching: {query}")
        logger.info(f"/play command in {msg.chat.id} by {msg.from_user.id}: {query}")

        info = await yt_search(query)
        if not info:
            return await msg.reply_text("❌ Failed to fetch audio.")

        ok = await player.enqueue_and_maybe_start(
            msg.chat.id, info["url"], info["title"], info["duration"], msg.from_user.id
        )

        if ok:
            await msg.reply_text(f"▶️ Now playing: **{info['title']}**")
        else:
            await msg.reply_text(f"➕ Queued: **{info['title']}**")
    except Exception as e:
        logger.error(f"Error in /play: {e}")
        traceback.print_exc()
        await msg.reply_text("⚠️ Internal error in /play")

@bot.on_message(filters.command("skip") & filters.group)
async def skip_cmd(_, msg):
    try:
        await player.skip(msg.chat.id)
        await msg.reply_text("⏭ Skipped to next track!")
    except Exception as e:
        logger.error(f"Error in /skip: {e}")
        traceback.print_exc()

@bot.on_message(filters.command("stop") & filters.group)
async def stop_cmd(_, msg):
    try:
        await player.stop(msg.chat.id)
        await msg.reply_text("⏹ Stopped and cleared queue.")
    except Exception as e:
        logger.error(f"Error in /stop: {e}")
        traceback.print_exc()

# ─── Main ───────────────────────────────────────────────
async def main():
    try:
        await bot.start()
        await user.start()
        await player.start()
        logger.info("Bot is up and running ✅")
        await idle()
    except Exception as e:
        logger.error(f"MAIN LOOP CRASH: {e}")
        traceback.print_exc()
    finally:
        await bot.stop()
        await user.stop()

if __name__ == "__main__":
    asyncio.run(main())
