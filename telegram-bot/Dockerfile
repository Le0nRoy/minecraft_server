FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
# Mount scripts volume for backup triggering
CMD ["python", "bot.py"]
