import os
from pyrogram import Client

API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("Set API_ID and API_HASH env vars before running this.")
    raise SystemExit(1)

app = Client(name="gen", api_id=API_ID, api_hash=API_HASH)

async def main():
    async with app:
        s = await app.export_session_string()
        print("\nSESSION_STRING=" + s + "\n")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
