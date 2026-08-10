#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

host = os.environ["REGISTRY_HOST"]
run_id = os.environ["RUN_ID"]
repo = f"openkubes/machine/contract-{run_id}"
outside = f"not-granted/contract-{run_id}"
base = f"https://{host}"
username = open("/auth/username", encoding="utf-8").read().strip()
password = open("/auth/password", encoding="utf-8").read().strip()
context = ssl.create_default_context(cafile="/ca/ca.crt")
authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def request(method, path, data=None, headers=None, expected=(200,)):
    request_headers = {"Authorization": authorization}
    request_headers.update(headers or {})
    req = urllib.request.Request(urllib.parse.urljoin(base, path), data=data, headers=request_headers, method=method)
    try:
        response = urllib.request.urlopen(req, context=context, timeout=30)
        status = response.status
        body = response.read()
        response_headers = response.headers
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        response_headers = exc.headers
    if status not in expected:
        raise AssertionError(f"{method} {path} returned HTTP {status}, expected {expected}: {body[:200]!r}")
    return status, response_headers, body


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def upload_blob(repository, content):
    wanted = digest(content)
    _, headers, _ = request("POST", f"/v2/{repository}/blobs/uploads/", expected=(202,))
    location = headers.get("Location")
    if not location:
        raise AssertionError("blob upload response had no Location")
    separator = "&" if "?" in location else "?"
    request("PUT", f"{location}{separator}digest={urllib.parse.quote(wanted, safe=':')}", data=content,
            headers={"Content-Type": "application/octet-stream"}, expected=(201,))
    return wanted


def descriptor(media_type, content):
    return {"mediaType": media_type, "digest": digest(content), "size": len(content)}


request("GET", "/v2/", expected=(200,))
config = b"{}"
layer = ("registry-default-contract-" + run_id + "\n").encode()
config_digest = upload_blob(repo, config)
layer_digest = upload_blob(repo, layer)
manifest_obj = {
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "artifactType": "application/vnd.openkubes.contract.v1",
    "config": descriptor("application/vnd.oci.empty.v1+json", config),
    "layers": [descriptor("application/vnd.openkubes.contract.layer.v1", layer)],
}
manifest = json.dumps(manifest_obj, separators=(",", ":"), sort_keys=True).encode()
manifest_digest = digest(manifest)
request("PUT", f"/v2/{repo}/manifests/subject", data=manifest,
        headers={"Content-Type": manifest_obj["mediaType"]}, expected=(201,))
_, _, pulled = request("GET", f"/v2/{repo}/manifests/{manifest_digest}",
                       headers={"Accept": manifest_obj["mediaType"]}, expected=(200,))
if digest(pulled) != manifest_digest:
    raise AssertionError(f"digest pull mismatch: pushed {manifest_digest}, pulled {digest(pulled)}")
request("GET", f"/v2/{repo}/blobs/{config_digest}", expected=(200,))
_, _, pulled_layer = request("GET", f"/v2/{repo}/blobs/{layer_digest}", expected=(200,))
if pulled_layer != layer:
    raise AssertionError("pulled layer bytes differ from pushed bytes")

ref_layer = ("referrer-" + run_id + "\n").encode()
upload_blob(repo, ref_layer)
ref_obj = {
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "artifactType": "application/spdx+json",
    "config": descriptor("application/vnd.oci.empty.v1+json", config),
    "layers": [descriptor("application/spdx+json", ref_layer)],
    "subject": descriptor(manifest_obj["mediaType"], manifest),
}
ref_manifest = json.dumps(ref_obj, separators=(",", ":"), sort_keys=True).encode()
ref_digest = digest(ref_manifest)
request("PUT", f"/v2/{repo}/manifests/referrer", data=ref_manifest,
        headers={"Content-Type": ref_obj["mediaType"]}, expected=(201,))
_, _, referrers_body = request("GET", f"/v2/{repo}/referrers/{manifest_digest}",
                               headers={"Accept": "application/vnd.oci.image.index.v1+json"}, expected=(200,))
referrers = json.loads(referrers_body)
matches = [item for item in referrers.get("manifests", []) if item.get("digest") == ref_digest]
if len(matches) != 1 or matches[0].get("artifactType") != "application/spdx+json":
    raise AssertionError(f"Referrers response did not assert the pushed descriptor: {referrers!r}")

request("POST", f"/v2/{outside}/blobs/uploads/", expected=(403,))
print(f"OCI_DIGEST: pushed={manifest_digest} pulled={digest(pulled)} byte_equal=true")
print(f"REFERRERS_ASSERTED: subject={manifest_digest} referrer={ref_digest} artifactType=application/spdx+json")
print("AUTHZ_NEGATIVE: machine identity outside-prefix upload returned HTTP 403")
print("BOUNDARY: in-cluster OCI contract proven; kubelet image pull NOT proven")
print("RESULT: PASS")
