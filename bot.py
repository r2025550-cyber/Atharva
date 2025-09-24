import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls, idle
from pytgcalls.types.input_stream import InputAudioStream
from gtts import gTTS

logging.basicConfig(level=logging.INFO)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
GROUP_ID = os.getenv("GROUP_ID", "")

app = Client(session_name=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
pytgcalls = PyTgCalls(app)

async def tts_to_file(text: str, filename: str, lang: str = "hi"):
    tts = gTTS(text=text, lang=lang)
    tts.save(filename)
    return filename

@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def text_handler(client: Client, message: Message):
    text = message.text.strip()
    if not text:
        return

    logging.info(f"Received text: {text}")

    filename = f"cache_{message.id}.mp3"
    await tts_to_file(text, filename, lang="hi")

    await pytgcalls.join_group_call(
        int(GROUP_ID),
        InputAudioStream(
            filename
        )
    )

async def main():
    await app.start()
    await pytgcalls.start()
    logging.info("Bot started!")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
