#!/usr/bin/env python3
"""ship-scan.py — scan a unified diff for credential literals and estate addresses.

Why this exists, and why it is not the repository's secret guard: the existing guard matches
the *identifier* `password`, so it fires on every commit that touches this shelf, because the
tooling legitimately names variables `machine_password` and reads Secret keys called
`writer-password`. A guard that is overridden every single time is a guard nobody reads, and
the override is then a judgement call made under time pressure.

So this checks the thing that actually matters -- a credential *value* committed as a literal --
and deliberately does not flag a name, a Secret key, or a read from Kubernetes. A line reading
`machine_password = kube.secret_value(...)` is not a finding; a credential-shaped name assigned a
non-empty quoted literal is. The self-test below states both directions precisely.

Note the fixtures are assembled from parts rather than written out. A scanner whose own source
matches its own pattern would have to allowlist itself, and a "skip this file" exception is how a
real finding gets hidden later.

It also refuses this estate's addresses. The shelf discovers its address at run time through
`registry-defaults.sh`; a literal copy goes stale silently after a cluster recreate, and these
repositories are public.

Reads a unified diff on stdin, considers ADDED lines only, and exits 1 on any finding.

    git diff --cached | python3 tooling/ship-scan.py
    python3 tooling/ship-scan.py --self-test
"""
import re
import sys

# A credential VALUE: an assignment whose right-hand side is a non-empty quoted literal.
# Requires a quote, so a function call or another identifier is not a finding.
SECRET_NAME = r"(?:pass(?:wd|word)?|secret|token|apikey|api_key|credential)"
CREDENTIAL_LITERAL = re.compile(
    rf"""[A-Za-z0-9_.\-]*{SECRET_NAME}[A-Za-z0-9_.\-]*   # a name that suggests a credential
         \s*[:=]\s*                                      # assigned
         (['"])                                          # opening quote
         (?!\s*$)                                        # not an empty string
         ([^'"\n]{{4,}})                                 # at least 4 characters of value
         \1""",
    re.IGNORECASE | re.VERBOSE,
)

# Values that are obviously not credentials even though they sit in a credential-shaped name.
PLACEHOLDER = re.compile(
    r"^(?:\$|\{\{|<|x+$|redacted|changeme|example|placeholder|none|null|true|false|"
    r"secret_value|kube\.|os\.environ|sys\.)",
    re.IGNORECASE,
)

# This estate's addresses. The shelf must carry none of them.
ESTATE_ADDRESS = re.compile(r"\b192\.168\.100\.\d{1,3}\b")

FINDING = "{kind}: {path}: {line}"


def scan(diff: str) -> list[str]:
    findings: list[str] = []
    path = "<unknown>"
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:]
        stripped = line.strip()

        match = CREDENTIAL_LITERAL.search(line)
        if match and not PLACEHOLDER.match(match.group(2).strip()):
            findings.append(
                FINDING.format(kind="CREDENTIAL LITERAL", path=path, line=stripped[:120])
            )

        if ESTATE_ADDRESS.search(line):
            findings.append(
                FINDING.format(kind="ESTATE ADDRESS", path=path, line=stripped[:120])
            )
    return findings


Q = '"'
_ESTATE = "192.168.100." + "207"


def assign(name: str, value: str, op: str = " = ", added: bool = True, suffix: str = "") -> str:
    """Build a diff line without this source ever containing name-operator-quote adjacently."""
    return ("+" if added else "-") + name + op + Q + value + Q + suffix


def bare(line: str, added: bool = True) -> str:
    return ("+" if added else "-") + line


SELF_TEST = [
    # (diff line, must_flag, why)
    (assign("PASSWORD", "hunter2"), True, "a literal credential value"),
    (bare("machine_password = kube.secret_value(ns, s, " + Q + "machine-password" + Q + ")"),
     False, "a read from Kubernetes, not a value"),
    (bare("        human_password = kube.secret_value("), False,
     "the exact line the old guard fired on"),
    (bare("    " + Q + "writer-password" + Q), False, "a Secret key name on its own line"),
    (assign("token", "abcd1234efgh", op=": "), True, "a literal token in YAML"),
    (bare("password" + " = " + Q + Q), False, "an empty string is not a credential"),
    (bare("api_key = os.environ[" + Q + "API_KEY" + Q + "]"), False, "an environment read"),
    (assign("PASSWORD", "${REGISTRY_PASSWORD}"), False, "a shell placeholder"),
    (bare("  address: " + _ESTATE), True, "this estate's MetalLB address"),
    (bare("  address: 10.35.1.133"), False,
     "a cluster-internal address is not the estate literal"),
    (assign("PASSWORD", "hunter2", added=False), False, "a REMOVED line is not a finding"),
    (assign("# password", "hunter2", suffix=" is what NOT to write"), True,
     "a literal in a comment is still a literal"),
]


def self_test() -> int:
    failures = 0
    for line, must_flag, why in SELF_TEST:
        got = bool(scan("+++ b/test.py\n" + line))
        ok = got == must_flag
        if not ok:
            failures += 1
        print(f"  {'ok  ' if ok else 'FAIL'}  flagged={got!s:5} expected={must_flag!s:5}  {why}")
    print()
    if failures:
        print(f"RESULT: FAIL - {failures} self-test case(s) wrong", file=sys.stderr)
        return 1
    print(f"RESULT: PASS - {len(SELF_TEST)} self-test cases, both directions")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    findings = scan(sys.stdin.read())
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        print(
            f"RESULT: FAIL - {len(findings)} finding(s) in ADDED lines. These are values, not "
            "names: read each one before deciding it is a false positive.",
            file=sys.stderr,
        )
        return 1
    print("RESULT: PASS - no credential literal or estate address in the added lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
