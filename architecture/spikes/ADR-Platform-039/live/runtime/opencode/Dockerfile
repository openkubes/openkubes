ARG NODE_IMAGE
FROM ${NODE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/* \
 && npm install --global opencode-ai@1.18.33 \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin workspace \
 && git config --system --add safe.directory /workspace
COPY checkout entrypoint.sh /usr/local/bin/
RUN chmod 0555 /usr/local/bin/checkout /usr/local/bin/entrypoint.sh
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
