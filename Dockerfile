# syntax=docker/dockerfile:1

ARG VERSION

FROM docker.io/library/python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone upstream repo (strip 'v' prefix if present)
RUN git clone --depth 1 --branch ${VERSION#v} https://github.com/Boof-Pack/token-enhancer.git /src

WORKDIR /src

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 8080

# Run the proxy server
CMD ["python3", "proxy.py"]
