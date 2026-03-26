# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy.py data_proxy.py mcp_server.py optimizer.py test_all.py ./

EXPOSE 8080

CMD ["python", "proxy.py"]
