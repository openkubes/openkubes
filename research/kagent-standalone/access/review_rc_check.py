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

Reports every point, then exits non-zero if any is unmet — the whole list matters,
not just the first failure. No cluster, no network.
"""
import importlib.util, pathlib, re, subprocess, sys, tempfile, yaml

ACC = pathlib.Path(__file__).resolve().parent
ROOT = ACC.parents[2]
spec = importlib.util.spec_from_file_location("ra", ACC / "render-access.py")
ra = importlib.util.module_from_spec(spec); spec.loader.exec_module(ra)

WORK = tempfile.TemporaryDirectory()
WORKDIR = pathlib.Path(WORK.name)

fails = []
def ck(ok, label, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok: fails.append(label)

def refused(cfg, label, needle):
    """Refused *for the stated reason*.

    A bare "some ConfigError was raised" check passes even when the refusal comes
    from an unrelated invariant — so deleting the very check the label names would
    not fail this file. The needle makes each PASS mean what its label says.
    """
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(cfg))
        try:
            ra.load_config(p, quiet=True)
        except ra.ConfigError as e:
            if needle.lower() in str(e).lower():
                print(f"  PASS  {label}\n          -> {str(e)[:110]}...")
            else:
                ck(False, label, f"refused for the wrong reason: {e}")
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
refused(profile(scope="cluster", namespaces=[]), "scope=cluster refused by render-access.py itself", "write.scope: 'cluster' is refused")
refused(profile(scope="cluster", namespaces=["kagent-lab"]), "scope=cluster + list refused", "write.scope: 'cluster' is refused")
src = txt("research/kagent-standalone/access/render-access.py")
# Look for the *emitter*, not the word: prose and error messages legitimately
# discuss ClusterRoleBinding, and a substring check on those produced a false
# positive the moment the docstring was expanded.
emitters = re.findall(r"""["']kind["']\s*:\s*["'](Cluster\w+)["']""", src)
ck(not emitters, "no ClusterRole/ClusterRoleBinding is constructed anywhere in the renderer", str(emitters))
with tempfile.TemporaryDirectory() as t:
    p=pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(profile()))
    out=pathlib.Path(t)/"o"; ra.write_outputs(ra.load_config(p, quiet=True), out, p, None)
    kinds=[d["kind"] for f in out.rglob("*.yaml") for d in yaml.safe_load_all(f.read_text()) if d and "kind" in d]
    # `Namespace` is cluster-scoped but expected: it is the tool server's own
    # namespace. The claim is about cluster-scoped *RBAC*.
    ck(not [k for k in kinds if k.startswith("Cluster")], "no cluster-scoped RBAC object is rendered", str(kinds))

print("\nRC2 — modular namespaced resource allow-list")
supported = {"configmaps", "pods", "services", "deployments", "statefulsets",
             "daemonsets", "replicasets", "jobs", "cronjobs", "ingresses"}
ck(set(ra.WRITABLE_RESOURCES)==supported, "WRITABLE_RESOURCES contains the supported namespaced kinds", str(sorted(ra.WRITABLE_RESOURCES)))
ck(ra.EVIDENCED_WRITE_NAMESPACES=={"kagent-lab"}, "EVIDENCED_WRITE_NAMESPACES == {kagent-lab}")
refused(profile(namespaces=["team-a"]), "an unevidenced namespace is refused", "exactly the evidenced target")
refused(profile(namespaces=["kagent-lab", "team-a"]), "a mixed namespace list is refused", "exactly the evidenced target")
for r in sorted(supported):
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t)/"c.yaml"; p.write_text(yaml.safe_dump(profile(resources=[r])))
        try:
            ra.load_config(p, quiet=True)
            ck(True, f"resources=[{r}] accepted")
        except ra.ConfigError as exc:
            ck(False, f"resources=[{r}] accepted", str(exc))
for r in ("secrets", "clusterroles", "*"):
    refused(profile(resources=[r]), f"resources=[{r}] refused", "can never be granted")
refused(profile(requireApproval=False), "requireApproval=false refused", "requireApproval: must be true")
ex = yaml.safe_load(txt("research/kagent-standalone/access/access-config.example.yaml"))
ck(set(ex["write"]["resources"]) == supported, "shipped example selects the complete OK-129 resource set", str(ex["write"]["resources"]))
ck(ex["write"]["namespaces"]==["kagent-lab"], "shipped example: namespaces == [kagent-lab]")
ck(ex["write"]["scope"]=="namespaces", "shipped example: scope == namespaces")

print("\nFollow-up — ports are actual integers, never coerced")
for field in ("port", "metricsPort"):
    for value in (True, False, 8084.9, "8084", None):
        ts={"namespace":"kagent-write","releaseName":"kagent-write-tools","port":8084,"metricsPort":8085}
        ts[field]=value
        refused(profile(toolServer=ts), f"{field}={value!r} refused", "expected an integer")

print("\nFollow-up — the v1 boundary holds for an importer, not only via load_config")
# The reviewer's point about the shared renderer applies to BOTH halves of the
# scope. A namespace allow-list enforced only in load_config is enforced only for
# callers that use load_config — the same gap as leaving it to each consumer.
def _hand_built(**over):
    w={"scope":"namespaces","namespaces":["kagent-lab"],"resources":["configmaps"],
       "require_approval":True,"tool_server_namespace":"kagent-write",
       "tool_server_release":"kagent-write-tools","tool_server_port":8084,
       "tool_server_metrics_port":8085,"tools":["k8s_apply_manifest"],
       "agent_name":"cluster-operator-gated"}
    w.update(over)
    return w, {"mode":"read-write","install_namespace":"kagent",
               "read":{"scope":"cluster","secrets":False,"tools":["k8s_get_resources"]},"write":w}

for label, over in (("cluster scope", {"scope":"cluster","namespaces":[]}),
                    ("namespaces=['prod-payments']", {"namespaces":["prod-payments"]}),
                    ("namespaces=['kagent-lab','team-a']", {"namespaces":["kagent-lab","team-a"]}),
                    ("namespaces=['kagent-lab','kagent-lab']", {"namespaces":["kagent-lab","kagent-lab"]}),
                    ("resources=['secrets']", {"resources":["secrets"]}),
                    ("agent_name with shell metacharacters", {"agent_name":"a'; id; #"}),
                    ("tool_server_namespace with shell metacharacters", {"tool_server_namespace":"x'; id; #"}),
                    ("require_approval=False", {"require_approval":False})):
    w, c = _hand_built(**over)
    for name, call in (("render_read_values", lambda: ra.render_read_values(c)),
                       ("render_namespace", lambda: ra.render_namespace(c)),
                       ("render_rbac", lambda: ra.render_rbac(c)),
                       ("render_tool_server", lambda: ra.render_tool_server(c)),
                       ("render_agent", lambda: ra.render_agent(c)),
                       ("render_tools_values", lambda: ra.render_tools_values(c, None)),
                       ("render_summary", lambda: ra.render_summary(c, pathlib.Path("x"))),
                       ("render_profile_env", lambda: ra.render_profile_env(c)),
                       ("write_outputs", lambda: ra.write_outputs(c, WORKDIR/"o", pathlib.Path("x"), None))):
        try:
            call(); ck(False, f"{name} accepted {label} (bypassing load_config)")
        except ra.ConfigError: ck(True, f"{name} refuses {label} without load_config")
        except AssertionError: ck(False, f"{name} guards {label} with assert, stripped by python3 -O")
        except Exception as exc: ck(False, f"{name} raised {type(exc).__name__} for {label}")
w, c = _hand_built()
ck({o["metadata"]["namespace"] for o in ra.render_rbac(c)} == {"kagent-lab"},
   "the evidenced hand-built dict still renders, in kagent-lab only")
ck("KAGENT_WRITE_NAMESPACES='kagent-lab'" in ra.render_profile_env(c),
   "profile.env publishes exactly the evidenced namespace")

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

WORK.cleanup()

print("\n" + ("="*60))
print(f"FAILED: {len(fails)}" if fails else "ALL RC CHECKS PASS")
for f in fails: print(" -", f)
sys.exit(1 if fails else 0)
