import asyncio
import os
from pyrogram import Client, filters, idle
from dotenv import load_dotenv
from loguru import logger

# Load .env if present
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Create bot client
bot = Client("butki_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@bot.on_message(filters.all)
async def debug_all(client, message):
    logger.info(
        f"📩 Received: {message.text} from {message.from_user.id if message.from_user else 'unknown'} "
        f"in chat {message.chat.id}"
    )
    try:
        await message.reply_text(f"Echo: {message.text}")
    except Exception as e:
        logger.error(f"Reply failed: {e}")


async def main():
    logger.info("🚀 Starting bot with force polling...")
    await bot.start()
    me = await bot.get_me()
    logger.info(f"🤖 Bot logged in as {me.first_name} (@{me.username}) [id={me.id}]")
    await idle()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
