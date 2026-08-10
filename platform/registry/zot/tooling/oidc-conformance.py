#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar

registry_host = os.environ["REGISTRY_HOST"]
keycloak_host = os.environ.get("KEYCLOAK_HOST", "keycloak.ok-shared.internal")
lb_ip = os.environ["REGISTRY_LB"]
# Required, not defaulted: these identify realm objects that `make oidc-client` reconciled
# from the same Makefile variables. A default here can silently disagree with what was
# actually created, and asserting against a stale group that still exists passes while
# testing something the registry no longer uses.
realm = os.environ["PLATFORM_REALM"]
client_id = os.environ["CLIENT_ID"]
writer_group = os.environ["WRITER_GROUP"]
reader_group = os.environ["READER_GROUP"]
run_id = os.environ["RUN_ID"]
ca_file = os.environ["CA_FILE"]
admin_username = os.environ["KEYCLOAK_ADMIN_USERNAME"]

# .strip() for parity with the shell tooling: $(cat <&3) and curl's password@file both
# strip, so a VSO-materialised value ending in a newline would 401 here and nowhere else.
admin_password = os.fdopen(3).read().strip()
writer_password = os.fdopen(4).read().strip()
reader_password = os.fdopen(5).read().strip()
oidc_credentials = json.loads(os.fdopen(6).read())
writer_username = os.environ["WRITER_USERNAME"]
reader_username = os.environ["READER_USERNAME"]
client_secret = oidc_credentials["clientsecret"]

real_getaddrinfo = socket.getaddrinfo


def fixed_getaddrinfo(host, port, *args, **kwargs):
    if host in (registry_host, keycloak_host):
        return real_getaddrinfo(lb_ip, port, *args, **kwargs)
    return real_getaddrinfo(host, port, *args, **kwargs)


socket.getaddrinfo = fixed_getaddrinfo
tls = ssl.create_default_context(cafile=ca_file)
registry = f"https://{registry_host}"
keycloak = f"https://{keycloak_host}"


def http(opener, method, url, data=None, headers=None, expected=(200,)):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        response = opener.open(req, timeout=30)
        status, response_headers, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        status, response_headers, body = exc.code, exc.headers, exc.read()
    if status not in expected:
        raise AssertionError(f"{method} {url} returned HTTP {status}, expected {expected}: {body[:240]!r}")
    return status, response_headers, body


plain = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls))


def form_post(url, fields, expected=(200,)):
    encoded = urllib.parse.urlencode(fields).encode()
    return http(plain, "POST", url, encoded, {"Content-Type": "application/x-www-form-urlencoded"}, expected)


_, _, admin_body = form_post(
    f"{keycloak}/realms/master/protocol/openid-connect/token",
    {"client_id": "admin-cli", "grant_type": "password", "username": admin_username, "password": admin_password},
)
admin_token = json.loads(admin_body)["access_token"]
admin_headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def kc_api(method, path, payload=None, expected=(200,)):
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    return http(plain, method, keycloak + path, data, admin_headers, expected)


def exact_one(items, key, wanted, label):
    matches = [item for item in items if item.get(key) == wanted]
    if len(matches) != 1:
        raise AssertionError(f"expected one {label} {wanted!r}, found {len(matches)}")
    return matches[0]


def lookup_group(name):
    _, _, body = kc_api("GET", f"/admin/realms/{realm}/groups?search={urllib.parse.quote(name)}&exact=true")
    return exact_one(json.loads(body), "name", name, "group")


def lookup_user(username):
    _, _, body = kc_api("GET", f"/admin/realms/{realm}/users?username={urllib.parse.quote(username)}&exact=true")
    return exact_one(json.loads(body), "username", username, "user")


def token_for(username, password):
    _, _, body = form_post(
        f"{keycloak}/realms/{realm}/protocol/openid-connect/token",
        {"client_id": client_id, "client_secret": client_secret, "grant_type": "password", "scope": "openid profile email",
         "username": username, "password": password},
    )
    token = json.loads(body)["access_token"]
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and (values.get("id") == "kc-form-login" or self.action is None):
            self.action = values.get("action")


def browser_api_key(username, password, label):
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls), urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("X-ZOT-API-CLIENT", "zot-ui")]
    _, _, page = http(opener, "GET", f"{registry}/zot/auth/login?provider=oidc", expected=(200,))
    parser = LoginForm()
    parser.feed(page.decode("utf-8", "replace"))
    if not parser.action:
        raise AssertionError("Keycloak login page had no login form action")
    login_data = urllib.parse.urlencode({"username": username, "password": password, "credentialId": ""}).encode()
    http(opener, "POST", parser.action, login_data, {"Content-Type": "application/x-www-form-urlencoded"}, expected=(200, 201))
    payload = json.dumps({"label": label}).encode()
    _, _, key_body = http(opener, "POST", f"{registry}/zot/auth/apikey", payload, {"Content-Type": "application/json"}, expected=(200, 201))
    return json.loads(key_body)["apiKey"]


def basic_header(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def registry_request(username, api_key, method, path, data=None, headers=None, expected=(200,)):
    combined = basic_header(username, api_key)
    combined.update(headers or {})
    return http(plain, method, registry + path, data, combined, expected)


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def upload_blob(username, api_key, repo, content):
    wanted = digest(content)
    _, headers, _ = registry_request(username, api_key, "POST", f"/v2/{repo}/blobs/uploads/", expected=(202,))
    location = headers["Location"]
    separator = "&" if "?" in location else "?"
    registry_request(username, api_key, "PUT", location + separator + "digest=" + urllib.parse.quote(wanted, safe=":"),
                     content, {"Content-Type": "application/octet-stream"}, expected=(201,))
    return wanted


def push_artifact(username, api_key, repo, tag, content):
    config = b"{}"
    upload_blob(username, api_key, repo, config)
    upload_blob(username, api_key, repo, content)
    manifest_obj = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.openkubes.oidc-conformance.v1",
        "config": {"mediaType": "application/vnd.oci.empty.v1+json", "digest": digest(config), "size": len(config)},
        "layers": [{"mediaType": "application/octet-stream", "digest": digest(content), "size": len(content)}],
    }
    manifest = json.dumps(manifest_obj, separators=(",", ":"), sort_keys=True).encode()
    registry_request(username, api_key, "PUT", f"/v2/{repo}/manifests/{tag}", manifest,
                     {"Content-Type": manifest_obj["mediaType"]}, expected=(201,))
    return digest(manifest), manifest_obj["mediaType"]


writer_group_obj = lookup_group(writer_group)
writer_user_obj = lookup_user(writer_username)
reader_claims = token_for(reader_username, reader_password)
if reader_group not in reader_claims.get("groups", []):
    raise AssertionError("reader token has no registry-readers group")
writer_claims = token_for(writer_username, writer_password)
if writer_group not in writer_claims.get("groups", []):
    raise AssertionError("writer token has no registry-writers group")
print("TOKEN_CLAIMS_PRESENT: " + json.dumps({"preferred_username": writer_claims.get("preferred_username"), "groups": writer_claims.get("groups")}, separators=(",", ":")))

repo = f"openkubes/human/oidc-{run_id}"
outside = f"not-granted/oidc-{run_id}"
writer_key = browser_api_key(writer_username, writer_password, f"ok138-writer-{run_id}")
manifest_digest, media_type = push_artifact(writer_username, writer_key, repo, "subject", f"writer-{run_id}\n".encode())
_, _, pulled = registry_request(writer_username, writer_key, "GET", f"/v2/{repo}/manifests/{manifest_digest}",
                                 headers={"Accept": media_type}, expected=(200,))
if digest(pulled) != manifest_digest:
    raise AssertionError("human digest pull differs from pushed digest")
registry_request(writer_username, writer_key, "POST", f"/v2/{outside}/blobs/uploads/", expected=(403,))
print(f"HUMAN_AUTHZ: granted push/pull digest={manifest_digest}; outside-prefix=403")

reader_key = browser_api_key(reader_username, reader_password, f"ok138-reader-{run_id}")
registry_request(reader_username, reader_key, "GET", f"/v2/{repo}/manifests/{manifest_digest}",
                 headers={"Accept": media_type}, expected=(200,))
registry_request(reader_username, reader_key, "POST", f"/v2/{repo}/blobs/uploads/", expected=(403,))
print("READ_ONLY_GROUP: granted pull=200; push=403")

removed = False
try:
    kc_api("DELETE", f"/admin/realms/{realm}/users/{writer_user_obj['id']}/groups/{writer_group_obj['id']}", expected=(204,))
    removed = True
    removed_claims = token_for(writer_username, writer_password)
    if writer_group in removed_claims.get("groups", []):
        raise AssertionError("removed writer group is still present in a newly issued token")
    print("TOKEN_CLAIMS_REMOVED: " + json.dumps({"preferred_username": removed_claims.get("preferred_username"), "groups": removed_claims.get("groups", [])}, separators=(",", ":")))
    removed_key = browser_api_key(writer_username, writer_password, f"ok138-removed-{run_id}")
    registry_request(writer_username, removed_key, "POST", f"/v2/{repo}/blobs/uploads/", expected=(403,))
    print("GROUP_DRIVEN_NEGATIVE: new token/session after membership removal lost granted-prefix access (HTTP 403)")
finally:
    if removed:
        kc_api("PUT", f"/admin/realms/{realm}/users/{writer_user_obj['id']}/groups/{writer_group_obj['id']}", expected=(204,))

restored_claims = token_for(writer_username, writer_password)
if writer_group not in restored_claims.get("groups", []):
    raise AssertionError("writer group was not restored in a new token")
restored_key = browser_api_key(writer_username, writer_password, f"ok138-restored-{run_id}")
registry_request(writer_username, restored_key, "GET", f"/v2/{repo}/manifests/{manifest_digest}",
                 headers={"Accept": media_type}, expected=(200,))
print("GROUP_RESTORED: new token carries registry-writers and pull returned HTTP 200")
print("RESULT: PASS — central OIDC and group-driven repository authorization asserted")
