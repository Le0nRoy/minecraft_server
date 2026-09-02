FROM python:3.12-slim
WORKDIR /app
# Install docker CLI for container stop/start via socket proxy
RUN apt-get update && apt-get install -y --no-install-recommends \
        docker.io \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
# Mount scripts volume for backup/wipe triggering
CMD ["python", "bot.py"]
