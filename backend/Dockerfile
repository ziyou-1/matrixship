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

# 生产服务器在大陆,直连 files.pythonhosted.org 会 ReadTimeout。线上镜像一直带着
# 这三个 PIP_* 环境变量,但 Dockerfile 里没有 —— 只要 requirements.txt 一变、pip
# 层缓存失效,镜像就再也构建不出来(2026-08-05 锁 bcrypt 版本时踩到)。这里补齐并
# 允许按需覆盖:境外构建可传 --build-arg PIP_INDEX_URL=https://pypi.org/simple。
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG PIP_DEFAULT_TIMEOUT=120
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}

RUN pip install --no-cache-dir --retries 5 -r requirements.txt

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
