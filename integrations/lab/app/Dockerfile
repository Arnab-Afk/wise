FROM python:3.12-slim
RUN pip install --no-cache-dir prometheus_client==0.21.0 opentelemetry-sdk==1.27.0 opentelemetry-exporter-otlp-proto-http==1.27.0
COPY app.py /app.py
CMD ["python", "/app.py"]
