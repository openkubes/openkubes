#!/usr/bin/env python3
"""Assert the five requested changes on PR #50, in the reviewer's own terms.

``render_access_test.py`` tests the renderer's behaviour. This file tests
something narrower and more specific: that each of RC1-RC5 from the review is
actually true of this tree — including in the *documents*, which no unit test
would otherwise cover.

It exists because the same five points came back twice. A reviewer should not
have to grep six markdown files to find out whether a claim was corrected, and a
future edit that quietly softens one of these back is a regression that should
fail a check rather than surface in a fourth review round.

Run from anywhere::

    python3 research/kagent-standalone/access/review_rc_check.py

Exits non-zero on the first unmet point. No cluster, no network.
"""
import importlib.util, pathlib, re, subprocess, sys, tempfile, yaml

ACC = pathlib.Path(__file__).resolve().parent
ROOT = ACC.parents[2]
spec = importlib.util.spec_from_file_location("ra", ACC / "render-access.py")
ra = importlib.util.module_from_spec(spec); spec.loader.exec_module(ra)

fails = []
def ck(ok, label, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok: fails.append(label)

def refused(cfg, label):
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(cfg))
        try:
            ra.load_config(p, quiet=True)
        except ra.ConfigError as e:
            print(f"  PASS  {label}\n          -> {str(e)[:110]}...")
            return
    ck(False, label, "ACCEPTED")

def profile(**w):
    write = {"scope":"namespaces","namespaces":["kagent-lab"],"resources":["configmaps"],
             "requireApproval":True,"toolServer":{"namespace":"kagent-write","releaseName":"kagent-write-tools"},
             "tools":["k8s_apply_manifest"]}
    write.update(w)
    return {"kind":"KagentAccessProfile","mode":"read-write","install":{"namespace":"kagent"},
            "read":{"scope":"cluster","secrets":False},"write":write}

def txt(p): return (ROOT/p).read_text(encoding="utf-8")

print("RC1 — write.scope: cluster removed from the SHARED renderer schema")
refused(profile(scope="cluster", namespaces=[]), "scope=cluster refused by render-access.py itself")
refused(profile(scope="cluster", namespaces=["kagent-lab"]), "scope=cluster + list refused")
src = txt("research/kagent-standalone/access/render-access.py")
ck("ClusterRoleBinding" not in src.split("PROTECTED_NAMESPACES")[0] and '"kind": "ClusterRoleBinding"' not in src,
   "no ClusterRoleBinding emitter anywhere in the renderer")
ck('"kind": "ClusterRole"' not in src, "no ClusterRole emitter anywhere in the renderer")
with tempfile.TemporaryDirectory() as t:
    p=pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(profile(namespaces=["kagent-lab","team-a"])))
    out=pathlib.Path(t)/"o"; ra.write_outputs(ra.load_config(p, quiet=True), out, p, None)
    kinds=[d["kind"] for f in out.rglob("*.yaml") for d in yaml.safe_load_all(f.read_text()) if d and "kind" in d]
    ck(not [k for k in kinds if k.startswith("Cluster")], f"nothing cluster-scoped rendered", str(kinds))

print("\nRC2 — v1 = ConfigMaps only, in THIS repo's renderer and docs")
ck(sorted(ra.WRITABLE_RESOURCES)==["configmaps"], "WRITABLE_RESOURCES == {configmaps}", str(sorted(ra.WRITABLE_RESOURCES)))
for r in ("deployments","statefulsets","daemonsets","replicasets","jobs","cronjobs","services","ingresses","pods"):
    refused(profile(resources=[r]), f"resources=[{r}] refused")
refused(profile(requireApproval=False), "requireApproval=false refused")
ex = yaml.safe_load(txt("research/kagent-standalone/access/access-config.example.yaml"))
ck(ex["write"]["resources"]==["configmaps"], "shipped example: resources == [configmaps]", str(ex["write"]["resources"]))
ck(ex["write"]["namespaces"]==["kagent-lab"], "shipped example: namespaces == [kagent-lab]")
ck(ex["write"]["scope"]=="namespaces", "shipped example: scope == namespaces")

print("\nRC3 — approval gate qualified, in access/README.md AND reference.md")
SENT = "shared write tool server and its Kubernetes identity are not"
for f in ("research/kagent-standalone/access/README.md","docs/kagent-standalone/reference.md",
          "docs/kagent-standalone/runbook.md","docs/kagent-standalone/evidence-protocol.md",
          "docs/kagent-standalone/README.md","research/kagent-standalone/README.md"):
    body = txt(f)
    ck(SENT in re.sub(r"[\s>*_]+", " ", body), f"{f}: states the tool server is NOT gated")
    ck("server-side" in body, f"{f}: names server-side enforcement as the requirement")
print("  -- generated SUMMARY.md --")
with tempfile.TemporaryDirectory() as t:
    p=pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(profile())); out=pathlib.Path(t)/"o"
    ra.write_outputs(ra.load_config(p, quiet=True), out, p, None)
    s=(out/"SUMMARY.md").read_text()
    ck("Agent-level policy" in s, "SUMMARY.md: gate called an Agent-level policy")
    ck(SENT in re.sub(r"[\s>*_]+", " ", s), "SUMMARY.md: tool server NOT gated")

print("\nRC4 — no unqualified 'never grants Secrets' / escalation claim")
BAD = ["can NOT read Secrets","cannot read Secrets","can not read Secrets","never grants Secrets",
       "never — not in any generated rule","privilege-escalation resources are refused",
       "no Secrets |","### What this profile can NOT do"]
for f in ("research/kagent-standalone/access/README.md","docs/kagent-standalone/reference.md",
          "docs/kagent-standalone/runbook.md","docs/kagent-standalone/evidence-protocol.md",
          "docs/kagent-standalone/README.md","research/kagent-standalone/README.md"):
    body = txt(f)
    hit=[b for b in BAD if b in body]
    ck(not hit, f"{f}: no absolute phrasing", str(hit))
for f in ("research/kagent-standalone/access/README.md","docs/kagent-standalone/reference.md"):
    body = txt(f)
    ck("no direct" in body.lower() and "permission" in body, f"{f}: claims 'no direct ... permission'")
    ck(all(k in body for k in ("serviceAccountName","admission")) or ("another ServiceAccount" in body and "admission" in body),
       f"{f}: indirect pod-template escalation caveat present")
    nb = re.sub(r"[\s>*_]+", " ", body).lower()
    ck("pod-template mutation" in nb and "deployment, statefulset, daemonset or job" in nb and "more privileged serviceaccount" in nb, f"{f}: names pod-template mutation, the four kinds, and the privileged SA")
with tempfile.TemporaryDirectory() as t:
    p=pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(profile())); out=pathlib.Path(t)/"o"
    ra.write_outputs(ra.load_config(p, quiet=True), out, p, None)
    s=(out/"SUMMARY.md").read_text()
    ck(not [b for b in BAD if b in s], "SUMMARY.md: no absolute phrasing")
    ck("no direct RBAC API permission" in s, "SUMMARY.md: 'no direct RBAC API permission'")
    ns = re.sub(r"[\s>*_]+", " ", s).lower()
    ck("pod-template mutation" in ns and "deployment, statefulset, daemonset or job" in ns and "more privileged serviceaccount in the same namespace" in ns and "admission control" in ns, "SUMMARY.md: indirect caveat with the reviewer's wording")

print("\nRC5 — governance placement")
ck(not (ROOT/"platform/ai/kagent-standalone").exists(), "platform/ai/kagent-standalone is gone")
ck((ROOT/"research/kagent-standalone/access/render-access.py").exists(), "assets live under research/")
ck((ROOT/"research/README.md").exists(), "research/README.md explains the placement")
# This file is excluded: it contains the string in order to search for it.
SELF = pathlib.Path(__file__).resolve().relative_to(ROOT).as_posix()
tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split("\0")
stale = "\n".join(
    t for t in tracked
    if t and t != SELF and "platform/ai/kagent-standalone" in (ROOT/t).read_text(errors="ignore")
)
ck(not stale, "no stale platform/ai/kagent-standalone reference in any TRACKED file", stale[:200])

print("\n" + ("="*60))
print(f"FAILED: {len(fails)}" if fails else "ALL RC CHECKS PASS")
for f in fails: print(" -", f)
sys.exit(1 if fails else 0)
