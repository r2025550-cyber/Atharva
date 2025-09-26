FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=on     PIP_NO_CACHE_DIR=on

WORKDIR /app

# FFmpeg for streaming
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg &&     rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "-m", "src.main"]
