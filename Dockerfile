FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential make tzdata \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r /app/requirements.txt

COPY . /app

RUN make build-zigzag

RUN mkdir -p /app/data /app/outputs /app/logs

CMD ["python", "get_most_cross_section_data.py", "--daemon", "--market", "all", "--interval-minutes", "15"]
