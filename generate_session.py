from pyrogram import Client
import os

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

if not API_ID or not API_HASH:
    print("Set API_ID and API_HASH env vars before running.")
    raise SystemExit(1)

with Client(name='gen', api_id=API_ID, api_hash=API_HASH) as app:
    print("SESSION_STRING=" + app.export_session_string())
