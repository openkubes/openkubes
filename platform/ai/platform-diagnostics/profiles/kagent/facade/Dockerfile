# Diagnostics facade image. GHCR is the primary registry (OK-15 decision).
#   docker build -t ghcr.io/openkubes/platform-diagnostics-facade:0.1.8 .
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# non-root (guideline: same posture as the openclaw image)
RUN useradd -u 1000 -m app
USER 1000

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
