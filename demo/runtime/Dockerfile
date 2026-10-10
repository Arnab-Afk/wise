FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY shopfront-template/requirements.txt /tmp/shopfront-requirements.txt
RUN pip install --no-cache-dir -r /tmp/shopfront-requirements.txt
COPY runtime/ /app/
ENV HOME=/tmp
ENTRYPOINT ["/app/entrypoint.sh"]
