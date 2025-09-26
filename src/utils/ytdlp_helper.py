import asyncio
from functools import partial
from yt_dlp import YoutubeDL

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "extract_flat": False,
    "default_search": "ytsearch",
    "nocheckcertificate": True,
    "geo_bypass": True,
}

def _extract(query: str):
    with YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        url = info.get("url") or info.get("webpage_url")
        duration = int(info.get("duration") or 0)
        title = info.get("title") or "Unknown"
        return {"url": url, "title": title, "duration": duration}

async def ytdlp_search_best(query: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_extract, query))
