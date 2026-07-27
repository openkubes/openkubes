# MCP adapter image — exposes the 3 contract functions as MCP tools over
# streamable-http, forwarding to the facade. Holds no kube credentials.
#   docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
#     -t ghcr.io/openkubes/platform-diagnostics-mcp-adapter:0.1.0 --push .
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

RUN useradd -u 1000 -m app
USER 1000

EXPOSE 8080
CMD ["python", "server.py"]
