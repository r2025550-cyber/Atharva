FROM python:3.10-slim

WORKDIR /app

# Install ffmpeg + git (needed for dev branch pytgcalls)
RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
