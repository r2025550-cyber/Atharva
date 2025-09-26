import yt_dlp
from typing import Optional, Tuple

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "nocheckcertificate": True,
    "extract_flat": False,
    "default_search": "auto",
    "geo_bypass": True,
    "cachedir": False,
}

def get_best_audio(url_or_query: str) -> Tuple[str, str, int]:
    """Return (stream_url, title, duration_seconds)."""
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url_or_query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        # Prefer direct URL if available, else fallback
        stream_url = info.get('url') or info.get('webpage_url')
        title = info.get('title', 'Unknown Title')
        duration = int(info.get('duration') or 0)
        return stream_url, title, duration
