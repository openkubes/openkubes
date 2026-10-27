#!/usr/bin/env python3
# C0 runtime/restart probe — Evidence-Server (Spike-Fixture für SPIKE-Platform-033).
#
# Trennt bewusst zwei Endpunkte:
#   /healthz   -> 200, solange der Prozess lebt. NICHT an Autonomy-Evidence gekoppelt.
#                 (Liveness/Readiness zeigen hierauf, damit ein DNS-/PVC-Ausfall den
#                  Container NICHT neu startet und der runtime-Drill nicht versehentlich
#                  restart-Semantik testet.)
#   /evidence  -> 200 nur, wenn DNS UND PVC aktuell und frisch PASS sind; sonst 503.
#                 Wird vom Drill über BEIDE Zugangswege (A Ingress, B ServiceLB) gescraped.
#
# Ein Hintergrund-Loop exercised aktiv, alle PROBE_INTERVAL_SECONDS:
#   - Cluster-DNS-Auflösung von DNS_PROBE_TARGET
#   - PVC Write->Read unter PVC_PROBE_PATH
import json, os, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DNS_TARGET  = os.environ.get("DNS_PROBE_TARGET", "runtime-probe.default.svc.cluster.local")
DATA_PATH   = os.environ.get("PVC_PROBE_PATH", "/data/heartbeat")
INTERVAL    = float(os.environ.get("PROBE_INTERVAL_SECONDS", "5"))
STALE_AFTER = float(os.environ.get("PROBE_STALE_AFTER_SECONDS", "15"))  # ~3 verpasste Zyklen

_state = {"dns": {"ok": False, "ts": 0.0, "detail": "init"},
          "pvc": {"ok": False, "ts": 0.0, "detail": "init"}}
_lock = threading.Lock()


def _check_dns():
    try:
        socket.getaddrinfo(DNS_TARGET, None)
        return True, "resolved"
    except Exception as e:
        return False, "resolve_failed:%s" % e.__class__.__name__


def _check_pvc():
    try:
        token = "%.6f" % time.time()
        with open(DATA_PATH, "w") as f:
            f.write(token)
        with open(DATA_PATH) as f:
            return (f.read() == token), "rw_ok"
    except Exception as e:
        return False, "rw_failed:%s" % e.__class__.__name__


def _loop():
    while True:
        now = time.time()
        dok, ddet = _check_dns()
        pok, pdet = _check_pvc()
        with _lock:
            _state["dns"] = {"ok": dok, "ts": now, "detail": ddet}
            _state["pvc"] = {"ok": pok, "ts": now, "detail": pdet}
        time.sleep(INTERVAL)


def _fresh(ts, now):
    return ts > 0 and (now - ts) <= STALE_AFTER


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            self._send(200, {"status": "ok"})            # entkoppelt von Autonomy-Evidence
            return
        if self.path.startswith("/evidence"):
            now = time.time()
            with _lock:
                dns = dict(_state["dns"]); pvc = dict(_state["pvc"])
            dns_pass = dns["ok"] and _fresh(dns["ts"], now)
            pvc_pass = pvc["ok"] and _fresh(pvc["ts"], now)
            ok = dns_pass and pvc_pass
            self._send(200 if ok else 503, {
                "evidence": "PASS" if ok else "FAIL",
                "dns": {"pass": dns_pass, "ok": dns["ok"], "detail": dns["detail"],
                        "ageSeconds": round(now - dns["ts"], 3) if dns["ts"] else None},
                "pvc": {"pass": pvc_pass, "ok": pvc["ok"], "detail": pvc["detail"],
                        "ageSeconds": round(now - pvc["ts"], 3) if pvc["ts"] else None},
                "target": DNS_TARGET, "path": DATA_PATH,
                "staleAfterSeconds": STALE_AFTER, "timestamp": now,
            })
            return
        self._send(404, {"status": "not_found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
