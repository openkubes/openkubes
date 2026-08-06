FROM python:3.13-alpine

WORKDIR /app
COPY server.py /app/server.py

USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["python", "/app/server.py", "--host", "0.0.0.0", "--port", "8080"]
