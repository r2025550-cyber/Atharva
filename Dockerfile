FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for ffmpeg, av, pytgcalls
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
    gcc \
    g++ \
    make \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
