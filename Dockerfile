FROM ghcr.io/thehamkercat/pytgcalls:latest
WORKDIR /app
COPY . /app
CMD ["python", "bot.py"]
