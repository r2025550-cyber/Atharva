import asyncio
import os
import traceback
from loguru import logger
from pyrogram import Client, filters, idle
from dotenv import load_dotenv

from .player import Player

# Load env vars
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Debugging ENV check
logger.info(f"API_ID={API_ID}, BOT_TOKEN={'set' if BOT_TOKEN else 'MISSING'}, SESSION={'set' if SESSION_STRING else 'MISSING'}")

# Clients
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
player = Player(user)


# ✅ Debug ALL incoming messages
@bot.on_message(filters.all)
async def debug_all(_, msg):
    try:
        logger.info(f"Message received: chat={msg.chat.id}, user={msg.from_user.id if msg.from_user else 'anon'}, text={msg.text}")
    except Exception as e:
        logger.error(f"Error in debug_all: {e}")
        traceback.print_exc()


# ✅ /start command
@bot.on_message(filters.command("start"))
async def start_cmd(_, msg):
    try:
        await msg.reply_text("✅ Bot is working! Send /play <song>")
        logger.info(f"/start handled in chat={msg.chat.id}")
    except Exception as e:
        logger.error(f"Error in /start: {e}")
        traceback.print_exc()


# ✅ /help command
@bot.on_message(filters.command("help"))
async def help_cmd(_, msg):
    await msg.reply_text("ℹ️ Commands:\n/start - check bot\n/play <song> - play music")


# Main entry
async def main():
    await bot.start()
    me = await bot.get_me()
    logger.info(f"Bot logged in as: {me.first_name} (@{me.username})")

    await user.start()
    await player.start()

    logger.info("Bot is up and running ✅")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
