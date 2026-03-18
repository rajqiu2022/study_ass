FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/instance /app/obsidian_vaults

EXPOSE 8088

CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "2", "--timeout", "120", "--preload", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
