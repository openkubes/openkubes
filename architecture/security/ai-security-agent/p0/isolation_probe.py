"""Check representative sandbox boundaries; does not prove all possible escapes."""
import json
import os
import socket

checks = {}
checks["host_path_hidden"] = not os.path.exists("/mnt/data")
checks["etc_hidden"] = not os.path.exists("/etc/passwd")
checks["ambient_secret_missing"] = "LEAK_TEST_SECRET" not in os.environ
try:
    with open("/work/probe-write-test", "w") as fp:
        fp.write("bad")
    checks["workspace_readonly"] = False
except OSError:
    checks["workspace_readonly"] = True
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.4)
        connection.connect(("1.1.1.1", 443))
    checks["network_denied"] = False
except OSError:
    checks["network_denied"] = True
print(json.dumps(checks, sort_keys=True))
if not all(checks.values()):
    raise SystemExit(1)
