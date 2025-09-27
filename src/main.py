import asyncio
import os
from pyrogram import Client, filters, idle
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.all)
async def echo_all(_, msg):
    logger.info(f"Received: {msg.text} from {msg.from_user.id if msg.from_user else 'anon'} in chat {msg.chat.id}")
    await msg.reply_text(f"Echo: {msg.text}")

async def main():
    await bot.start()
    me = await bot.get_me()
    logger.info(f"✅ Bot logged in as {me.first_name} (@{me.username})")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
