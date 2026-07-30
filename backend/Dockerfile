FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN python --version && node --version && npm --version

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
EXPOSE 9080

ENV PYTHONUNBUFFERED=1
ENV NODE_ENV=production
ENV CENTRAL_HOST=0.0.0.0
ENV CENTRAL_PORT=9080
ENV CENTRAL_DATA_DIR=/app/central_data

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('CENTRAL_PORT','9080'); urllib.request.urlopen('http://127.0.0.1:%s/api/health' % port, timeout=3).read()"

CMD ["python", "central_server.py"]
