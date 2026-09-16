# Use official lightweight Python image
FROM python:3.14-slim AS base

# Prevent Python from writing .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    make \
    locales && \
    rm -rf /var/lib/apt/lists/* && \
    sed -i '/es_ES.UTF-8/s/^# //' /etc/locale.gen && \
    locale-gen && \
    update-locale LANG=es_ES.UTF-8

ENV LANG=es_ES.UTF-8
ENV LANGUAGE=es_ES:es
ENV LC_ALL=es_ES.UTF-8
ENV CONTAINER=1

# dev stage: system env only; code is volume-mounted, deps installed at startup
FROM base AS dev

RUN apt-get update && apt-get install -y --no-install-recommends \
    git

RUN git config --global --add safe.directory /app

# production stage (default): install and run
FROM base
COPY pyproject.toml .
COPY Makefile .
COPY src ./src
RUN make install
ENTRYPOINT ["python", "-m", "justicier"]
CMD []
