#!/usr/bin/env bash
#
# OK-211 — `make verify`: every pass criterion that can be checked without a
# new measurement (BRIEF B8, Phase 12).
#   1. knative-verify (deployments, webhooks, overrides, gateway digest)
#   2. smoke: podinfo through Kourier -> 200
#   3. release dry run for 1.24 (no SSA conflict with the derivation rules)
#   4. evidence files, REPORT.md, MANAGEMENT-SUMMARY.md present
#   5. measurements.json: every line has the B11 fields; every required series present
#   6. BRIEF.md unchanged (sha256 as handed over)
# Exit 1 if any check fails. The caller (make) runs the guard with --node first.

# check always returns 0, so "A && check … || check …" cannot run both branches.
# shellcheck disable=SC2015
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
cd "$SPIKE_ROOT"
fail=0
check() { if [ "$2" = ok ]; then printf '  PASS %s\n' "$1"; else printf '  FAIL %s (%s)\n' "$1" "$2"; fail=1; fi; }

"$SCRIPT_DIR/knative.sh" verify >/dev/null 2>&1 && check "knative-verify" ok || check "knative-verify" "see make knative-verify"
code="$("$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 60 -w '%{http_code}' \
  -H "Host: podinfo.ok211-serving.$KNATIVE_DOMAIN" http://kourier.kourier-system.svc.cluster.local/ 2>/dev/null || true)"
[ "$code" = 200 ] && check "smoke podinfo" ok || check "smoke podinfo" "http $code"
"$SCRIPT_DIR/knative.sh" dry-run 1.24 >/dev/null 2>&1 && check "release dry run 1.24 (no SSA conflict)" ok || check "release dry run 1.24" "see make knative-dry-run TO=1.24"

missing=""
for f in evidence/00-preflight.md evidence/01-vm-k3s.md evidence/02-knative-install.md evidence/03-upgrade.md \
         evidence/04-serving.md evidence/05-eventing.md evidence/06-networking-tls.md evidence/07-security.md \
         evidence/08-gitops.md evidence/09-architecture-assessment.md REPORT.md MANAGEMENT-SUMMARY.md \
         drafts/jira-comment.md drafts/pr-description.md; do
  [ -s "$f" ] || missing="$missing $f"
done
[ -z "$missing" ] && check "evidence and report files present" ok || check "evidence and report files present" "missing:$missing"

bad="$(jq -c 'select((has("id") and has("timestamp_utc") and has("knative_version") and has("config") and has("runs") and has("stats") and has("notes")) | not) | .id' evidence/raw/measurements.json | tr '\n' ' ')"
[ -z "$bad" ] && check "measurements.json lines carry the B11 fields" ok || check "measurements.json B11 fields" "lines without: $bad"
need="U1 U2 S2 S3 S4 S5 S6 S7 S8 S9 S10 E1 E2 E3 E4 E5-dispatcher E5-ingress E5-restart E5-none E6 E8 N1 N4 X1 X2 X3 X5 X6"
have="$(jq -r '.id' evidence/raw/measurements.json | sort -u | tr '\n' ' ')"
absent=""
for id in $need; do case " $have " in *" $id "*) : ;; *) absent="$absent $id" ;; esac; done
[ -z "$absent" ] && check "required series in measurements.json ($(echo "$need" | wc -w | tr -d ' '))" ok || check "required series" "absent:$absent"

sum="$(shasum -a 256 BRIEF.md | awk '{print $1}')"
[ "$sum" = fd96141bfd574455d398bcb2f4cefab9594672852315c9f6a6d1c6b8e335fac5 ] && check "BRIEF.md unchanged" ok || check "BRIEF.md unchanged" "sha256 $sum"

[ "$fail" -eq 0 ] || ok211::die "verify: at least one check failed" 1
ok211::ok "verify: all checks passed"
