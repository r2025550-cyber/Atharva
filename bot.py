import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import GroupCallFactory
from gtts import gTTS

logging.basicConfig(level=logging.INFO)

# Load env vars
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
GROUP_ID = os.getenv("GROUP_ID", "")

# Initialize Pyrogram client
app = Client(
    session_string=SESSION_STRING,
    api_id=API_ID,
    api_hash=API_HASH
)

# Initialize GroupCallFactory
group_call = GroupCallFactory(app).get_group_call()

async def tts_to_file(text: str, filename: str, lang: str = "hi"):
    """Convert text to speech and save as mp3"""
    tts = gTTS(text=text, lang=lang)
    tts.save(filename)
    return filename

@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def text_handler(client: Client, message: Message):
    """When text comes in channel, convert to speech and play in VC"""
    text = message.text.strip()
    if not text:
        return

    logging.info(f"Received text: {text}")

    filename = f"cache_{message.id}.mp3"
    await tts_to_file(text, filename, lang="hi")

    try:
        if not group_call.is_connected:
            await group_call.join(int(GROUP_ID))
        await group_call.start_audio(filename)
        logging.info("Playing audio in VC")
    except Exception as e:
        logging.error(f"Error while playing audio: {e}")

async def main():
    await app.start()
    logging.info("Bot started! Waiting for messages...")
    await asyncio.Future()  # keep running forever

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
