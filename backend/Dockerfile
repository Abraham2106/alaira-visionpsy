# Imagen Python 3.11 de VisionPsy-Local; publicar su puerto solo en loopback o IP LAN.
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend /app/backend
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "backend.main:configured_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--ws-max-size", "2000000"]
