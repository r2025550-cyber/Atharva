FROM python:3.10-slim


WORKDIR /app


# Install ffmpeg and dependencies
RUN apt-get update && apt-get install -y \
ffmpeg \
build-essential \
&& rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .


# Optional: healthcheck to auto-restart if process crashes
HEALTHCHECK CMD pgrep -f "python bot.py" || exit 1


CMD ["python", "bot.py"]
