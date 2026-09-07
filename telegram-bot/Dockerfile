FROM python:3.12-slim
# Fetch rcon-cli binary from the official itzg image
COPY --from=itzg/rcon-cli:latest /rcon-cli /usr/local/bin/rcon-cli
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
