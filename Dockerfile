
# Use a slim Python base (change to 3.10/3.11 if you prefer)
FROM python:3.11-slim

# Avoid interactive prompts from apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps required to build and run PyAV, ffmpeg-based stuff, and pytgcalls
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    git \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavdevice-dev \
    libavfilter-dev \
    libavutil-dev \
    libswscale-dev \
    libopus-dev \
    libssl-dev \
    python3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY . /app

# Create a non-root user to run container (improves security)
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

# Environment example (override with docker run -e or .env)
ENV BOT_CONFIG=/app/.env

# Default command (replace run.py with your bot's entrypoint)
CMD ["python", "run.py"]
