ARG NODE_IMAGE
FROM ${NODE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends git python3 curl ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin fixture
COPY server.py entrypoint.sh /usr/local/bin/
RUN chmod 0555 /usr/local/bin/entrypoint.sh /usr/local/bin/server.py \
 && mkdir -p /srv/git && chown -R fixture:fixture /srv/git
USER 10001:10001
EXPOSE 8080 8081 8443
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
