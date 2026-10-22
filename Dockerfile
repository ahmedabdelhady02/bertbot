FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/counters.db

WORKDIR /app

RUN useradd --create-home --uid 10001 bot \
    && mkdir /data \
    && chown bot:bot /data

RUN pip install --no-cache-dir discord.py python-dotenv

COPY bot.py config.py database.py dev.py utils.py ./
COPY cogs/ ./cogs/
COPY services/ ./services/

USER bot
VOLUME ["/data"]

CMD ["python", "bot.py"]
