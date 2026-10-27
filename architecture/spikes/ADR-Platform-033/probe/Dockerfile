# Spike-Fixture-Image für den C0 runtime/restart-Probe (SPIKE-Platform-033).
#
# Weil dieser Container SELBST Evidence erzeugt, ist er als Fixture zu behandeln:
# reproduzierbar bauen und VOR jeder runtime/restart-Evidence per Digest pinnen —
# kein Utility-Image zur Laufzeit ziehen.
#
#   docker build -t <registry>/okp-spike-runtime-probe:<ver> probe/
#   docker push  <registry>/okp-spike-runtime-probe:<ver>
#   # dann den @sha256:-Digest ins Manifest übernehmen (image: ...@sha256:<pin>)
#
# Nur Python-Stdlib (http.server, socket) — keine externen Abhängigkeiten, kein pip.
FROM python:3.12-slim@sha256:PIN-ME-BEFORE-EVIDENCE
WORKDIR /app
COPY app.py /app/app.py
EXPOSE 8080
# nonroot; PVC-Schreibrecht kommt über securityContext.fsGroup im Manifest
USER 65532:65532
ENTRYPOINT ["python3", "/app/app.py"]
