FROM python:3.10-slim

WORKDIR /app

# System dependencies (for ffmpeg + av)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavformat-dev \
    libavdevice-dev \
    libavfilter-dev \
    libavcodec-dev \
    libavutil-dev \
    libswresample-dev \
    libswscale-dev \
    libopus-dev \
    pkg-config \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Upgrade pip + setuptools + wheel
RUN pip install --upgrade pip setuptools wheel

# Install av from prebuilt wheel only (skip compiling)
RUN pip install av==9.2.0 --only-binary=:all:

# Install all Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
