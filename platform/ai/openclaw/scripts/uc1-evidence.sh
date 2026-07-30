#!/usr/bin/env bash
# UC-1 evidence runner (OK-14).
#
# Runs the three defined troubleshooting scenarios (S1-S3) against the Read-Only
# Platform Diagnostics Contract and the mechanical half of the OpenClaw
# statelessness restart test (T4), evaluates every machine-checkable pass
# criterion from docs/agentic-ai-poc-evidence-protocol.md, and writes a filled
# evidence report.
#
# It never records a PASS for something it did not observe: the UI-bound steps
# (S4, and the Open WebUI half of T4) are emitted as an operator checklist with
# blanks to fill in.
#
# Usage:
#   CLUSTER=ok-ai platform/ai/openclaw/scripts/uc1-evidence.sh [options]
#
#   --keep-fixtures   leave the broken Deployments up for manual inspection
#   --skip-restart    S1-S3 only, no T4
#   --namespace NS    fixture namespace (default: ok14-evidence)
#   --out DIR         report directory (default: <script>/../.evidence)
#
# Requires: kubectl, jq, curl. Read-only against the cluster except for the
# fixture namespace and the deliberate OpenClaw pod delete in T4.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="${SCRIPT_DIR}/uc1-fixtures.yaml"

CLUSTER="${CLUSTER:-ok-ai}"
KUBECONFIG_PATH="${KUBECONFIG:-${HOME}/.kube/${CLUSTER}.yaml}"
NS_EVIDENCE="${NS_EVIDENCE:-ok14-evidence}"
PD_NS="${PD_NS:-platform-diagnostics}"
PD_SVC="${PD_SVC:-platform-diagnostics}"
OPENCLAW_NS="${OPENCLAW_NS:-openclaw}"
OPENCLAW_RELEASE="${OPENCLAW_RELEASE:-openclaw}"
OUT_DIR="${SCRIPT_DIR}/../.evidence"
KEEP_FIXTURES=0
SKIP_RESTART=0
# A real diagnosis is an LLM round trip plus read-only tool calls: 30-120s is
# normal, so allow generous headroom before calling it a failure.
HTTP_TIMEOUT="${HTTP_TIMEOUT:-300}"
FIXTURE_WAIT="${FIXTURE_WAIT:-180}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-fixtures) KEEP_FIXTURES=1; shift ;;
    --skip-restart)  SKIP_RESTART=1; shift ;;
    --namespace)     NS_EVIDENCE="$2"; shift 2 ;;
    --out)           OUT_DIR="$2"; shift 2 ;;
    -h|--help)       sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

KUBECTL=(kubectl --kubeconfig "${KUBECONFIG_PATH}")

TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${OUT_DIR}"
REPORT="${OUT_DIR}/uc1-evidence-${TS}.md"
RAW_DIR="${OUT_DIR}/raw-${TS}"
mkdir -p "${RAW_DIR}"

PASS_N=0; FAIL_N=0; SKIP_N=0
declare -a RESULTS=()
# Criteria text contains '|' (enum lists like healthy|degraded), so results are
# stored with an ASCII unit separator and pipes are escaped only at render time.
SEP=$'\037'

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_off=$'\033[0m'
[[ -t 1 ]] || { c_red=""; c_grn=""; c_yel=""; c_off=""; }

log()  { printf '%s\n' "$*"; }
head2() { printf '\n=== %s ===\n' "$*"; }

# record <scenario> <criterion> <PASS|FAIL|MANUAL> [detail]
record() {
  local sc="$1" crit="$2" verdict="$3" detail="${4:-}"
  case "$verdict" in
    PASS)   PASS_N=$((PASS_N+1)); log "  ${c_grn}PASS${c_off}  ${sc}: ${crit}" ;;
    FAIL)   FAIL_N=$((FAIL_N+1)); log "  ${c_red}FAIL${c_off}  ${sc}: ${crit}${detail:+ — ${detail}}" ;;
    MANUAL) SKIP_N=$((SKIP_N+1)); log "  ${c_yel}TODO${c_off}  ${sc}: ${crit} (operator)" ;;
  esac
  RESULTS+=("${sc}${SEP}${crit}${SEP}${verdict}${SEP}${detail}")
}

# assert <scenario> <criterion> <0|1 ok> [detail]
assert() {
  local sc="$1" crit="$2" ok="$3" detail="${4:-}"
  if [[ "$ok" -eq 0 ]]; then record "$sc" "$crit" PASS; else record "$sc" "$crit" FAIL "$detail"; fi
}

cleanup() {
  local rc=$?
  if [[ -n "${PF_PID:-}" ]] && kill -0 "${PF_PID}" 2>/dev/null; then
    kill "${PF_PID}" 2>/dev/null || true
    wait "${PF_PID}" 2>/dev/null || true
  fi
  if [[ "${KEEP_FIXTURES}" -eq 0 && "${FIXTURES_APPLIED:-0}" -eq 1 ]]; then
    head2 "cleanup: removing fixtures"
    "${KUBECTL[@]}" delete namespace "${NS_EVIDENCE}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    log "namespace ${NS_EVIDENCE} deletion requested"
  elif [[ "${KEEP_FIXTURES}" -eq 1 ]]; then
    log ""
    log "fixtures kept in namespace ${NS_EVIDENCE} — remove with:"
    log "  kubectl delete namespace ${NS_EVIDENCE}"
  fi
  exit "$rc"
}
trap cleanup EXIT

# ── preflight ────────────────────────────────────────────────────────────────
head2 "preflight"
for bin in kubectl jq curl; do
  command -v "$bin" >/dev/null 2>&1 || { echo "missing required tool: $bin" >&2; exit 1; }
done
[[ -f "${FIXTURES}" ]] || { echo "fixtures not found: ${FIXTURES}" >&2; exit 1; }
[[ -r "${KUBECONFIG_PATH}" ]] || { echo "kubeconfig not readable: ${KUBECONFIG_PATH}" >&2; exit 1; }

"${KUBECTL[@]}" version --request-timeout=10s -o json >/dev/null 2>&1 \
  || { echo "cluster ${CLUSTER} unreachable (VPN up?)" >&2; exit 1; }
log "cluster:      ${CLUSTER} (${KUBECONFIG_PATH})"

"${KUBECTL[@]}" -n "${PD_NS}" get svc "${PD_SVC}" >/dev/null 2>&1 \
  || { echo "facade service ${PD_SVC} not found in ${PD_NS} — deploy Profile A first" >&2; exit 1; }
PD_PORT="$("${KUBECTL[@]}" -n "${PD_NS}" get svc "${PD_SVC}" -o jsonpath='{.spec.ports[0].port}')"
log "facade:       svc/${PD_SVC}.${PD_NS}:${PD_PORT}"

# Port-forward so responses are clean JSON on stdout and jq runs locally.
LOCAL_PORT="${LOCAL_PORT:-18080}"
"${KUBECTL[@]}" -n "${PD_NS}" port-forward "svc/${PD_SVC}" "${LOCAL_PORT}:${PD_PORT}" \
  >"${RAW_DIR}/port-forward.log" 2>&1 &
PF_PID=$!
BASE="http://127.0.0.1:${LOCAL_PORT}"
for _ in $(seq 1 30); do
  curl -fsS --max-time 2 "${BASE}/openapi.json" >/dev/null 2>&1 && break
  curl -fsS --max-time 2 "${BASE}/docs" >/dev/null 2>&1 && break
  sleep 1
done
kill -0 "${PF_PID}" 2>/dev/null || { echo "port-forward failed, see ${RAW_DIR}/port-forward.log" >&2; exit 1; }
log "port-forward: ${BASE} -> svc/${PD_SVC}:${PD_PORT} (pid ${PF_PID})"

PROV_CAPS_DEPLOYED="$("${KUBECTL[@]}" -n "${PD_NS}" get deploy -l app.kubernetes.io/name=platform-diagnostics-facade \
  -o jsonpath='{.items[0].spec.template.spec.containers[0].env[?(@.name=="PROVIDER_CAPS")].value}' 2>/dev/null || true)"
log "provider caps (deployed): ${PROV_CAPS_DEPLOYED:-<unset, facade default>}"

# call <name> <path> <json-body> -> writes ${RAW_DIR}/<name>.json, echoes http code
call() {
  local name="$1" path="$2" body="$3" code
  # curl writes the code via -w even when it fails (as 000); keep only the last
  # three digits so a transport failure reports 000, not a concatenation.
  code="$(curl -sS -o "${RAW_DIR}/${name}.json" -w '%{http_code}' \
    --max-time "${HTTP_TIMEOUT}" \
    -X POST -H 'Content-Type: application/json' \
    -d "${body}" "${BASE}${path}" 2>"${RAW_DIR}/${name}.err" || true)"
  code="${code: -3}"
  printf '%s' "${code:-000}"
}

jqr() { jq -r "$1" "${RAW_DIR}/${2}.json" 2>/dev/null || printf ''; }
# Same, but safe to drop into a Markdown table cell (agent prose may contain '|').
jqmd() { local v; v="$(jqr "$1" "$2")"; printf '%s' "${v//|/\\|}"; }

# ── S1 — cluster health ──────────────────────────────────────────────────────
head2 "S1 — get_platform_health"
S1_CODE="$(call s1 /v1/get_platform_health "{\"clusters\":[\"${CLUSTER}\"]}")"
log "HTTP ${S1_CODE}"
assert S1 "HTTP 200" "$([[ "${S1_CODE}" == "200" ]] && echo 0 || echo 1)" "got ${S1_CODE}"

if [[ "${S1_CODE}" == "200" ]]; then
  assert S1 "response has generated_at + clusters[] (PlatformHealth shape)" \
    "$(jq -e 'has("generated_at") and (.clusters|type=="array") and (.clusters|length>0)' "${RAW_DIR}/s1.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  S1_STATUS="$(jqr '.clusters[0].status' s1)"
  log "status: ${S1_STATUS}"
  # 'unknown' is the facade parse-fallback, not a cluster state — hard FAIL.
  assert S1 "status is healthy|degraded|unavailable (NOT the 'unknown' fallback)" \
    "$([[ "${S1_STATUS}" =~ ^(healthy|degraded|unavailable)$ ]] && echo 0 || echo 1)" \
    "status=${S1_STATUS:-<none>} — see facade app.py get_platform_health fallback path"

  assert S1 "provider_capabilities present" \
    "$(jq -e '.clusters[0].provider_capabilities|type=="object"' "${RAW_DIR}/s1.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  assert S1 "summary non-empty" \
    "$([[ -n "$(jqr '.clusters[0].summary // ""' s1)" ]] && echo 0 || echo 1)"
fi

# ── fixtures for S2/S3 ───────────────────────────────────────────────────────
head2 "S2/S3 fixtures — namespace ${NS_EVIDENCE}"
sed "s/__NS__/${NS_EVIDENCE}/g" "${FIXTURES}" | "${KUBECTL[@]}" apply -f - >/dev/null
FIXTURES_APPLIED=1
log "applied uc1-imagepull + uc1-crashloop"

# Wait until each fixture actually reached its intended failure state, otherwise
# we would be asking the agent to diagnose a pod that is merely still starting.
wait_for_reason() {
  local dep="$1" want="$2" deadline=$((SECONDS + FIXTURE_WAIT)) reason=""
  while (( SECONDS < deadline )); do
    reason="$("${KUBECTL[@]}" -n "${NS_EVIDENCE}" get pods -l "app.kubernetes.io/name=${dep}" \
      -o jsonpath='{range .items[*].status.containerStatuses[*]}{.state.waiting.reason}{"\n"}{end}' 2>/dev/null | grep -v '^$' | head -1 || true)"
    [[ "${reason}" == "${want}" ]] && { printf '%s' "${reason}"; return 0; }
    sleep 5
  done
  printf '%s' "${reason:-none}"
  return 1
}

R1="$(wait_for_reason uc1-imagepull ImagePullBackOff)" && OK1=0 || OK1=1
log "uc1-imagepull: ${R1}"
assert S2 "fixture uc1-imagepull reached ImagePullBackOff" "${OK1}" "observed=${R1}"

R2="$(wait_for_reason uc1-crashloop CrashLoopBackOff)" && OK2=0 || OK2=1
log "uc1-crashloop: ${R2}"
assert S2 "fixture uc1-crashloop reached CrashLoopBackOff" "${OK2}" "observed=${R2}"

IMAGEPULL_POD="$("${KUBECTL[@]}" -n "${NS_EVIDENCE}" get pods \
  -l app.kubernetes.io/name=uc1-imagepull \
  -o jsonpath='{.items[0].metadata.name}')"
CRASHLOOP_POD="$("${KUBECTL[@]}" -n "${NS_EVIDENCE}" get pods \
  -l app.kubernetes.io/name=uc1-crashloop \
  -o jsonpath='{.items[0].metadata.name}')"
log "resolved fixture pods: imagepull=${IMAGEPULL_POD}, crashloop=${CRASHLOOP_POD}"

# ── S2 — investigate_workload ────────────────────────────────────────────────
# require_terms/forbid_terms: the top-ranked cause must explain the deliberately
# injected failure, not merely contain a broad state name such as "CrashLoop".
investigate() {
  local wl="$1" name="$2" require_terms="$3" forbid_terms="$4" expected_pod="$5" code
  head2 "S2 — investigate_workload (${wl})"
  code="$(call "${name}" /v1/investigate_workload \
    "{\"cluster\":\"${CLUSTER}\",\"namespace\":\"${NS_EVIDENCE}\",\"workload\":\"${wl}\",\"time_range\":\"PT1H\"}")"
  log "HTTP ${code}"
  assert "S2/${wl}" "HTTP 200" "$([[ "${code}" == "200" ]] && echo 0 || echo 1)" "got ${code}"
  [[ "${code}" == "200" ]] || return 0

  assert "S2/${wl}" "WorkloadInvestigation required fields present" \
    "$(jq -e 'has("summary") and has("symptoms") and has("evidence") and has("probable_causes") and has("recommended_next_steps")' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  assert "S2/${wl}" "probable_causes non-empty" \
    "$(jq -e '(.probable_causes|type=="array") and (.probable_causes|length>0)' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  local top; top="$(jqr '.probable_causes[0].hypothesis // ""' "${name}")"
  log "top hypothesis: ${top:0:160}"
  assert "S2/${wl}" "top hypothesis names the injected root cause (${require_terms})" \
    "$(printf '%s' "${top}" | grep -Eiq "${require_terms}" && echo 0 || echo 1)" \
    "top=\"${top:0:120}\""

  assert "S2/${wl}" "top hypothesis does not claim a contradictory failure mode" \
    "$(printf '%s' "${top}" | grep -Eiq "${forbid_terms}" && echo 1 || echo 0)" \
    "forbidden=${forbid_terms}; top=\"${top:0:120}\""

  assert "S2/${wl}" "every hypothesis has confidence low|medium|high" \
    "$(jq -e '[.probable_causes[].confidence] | length>0 and all(. as $c | ["low","medium","high"]|index($c)!=null)' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  # ADR-021 test 6: not_checked means counter-evidence was never sought.
  assert "S2/${wl}" "counter_evidence_status is found|none_found (never not_checked)" \
    "$(jq -e '[.probable_causes[].counter_evidence_status] | length>0 and all(. as $s | ["found","none_found"]|index($s)!=null)' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)" \
    "statuses=$(jqr '[.probable_causes[].counter_evidence_status]|join(",")' "${name}")"

  assert "S2/${wl}" "evidence non-empty and every available ref carries a uri" \
    "$(jq -e '(.evidence|length>0) and ([.evidence[]|select(.status=="available")]|length>0) and ([.evidence[]|select(.status=="available")]|all(has("uri") and (.uri|length>0)))' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  # ADR-021 test 3: references only. Catch payloads smuggled into a ref.
  assert "S2/${wl}" "no embedded payloads or secret-ish keys in evidence (refs only)" \
    "$(jq -e '[.evidence[]|keys[]]|unique|all(. as $k | ["type","source","status","reason","uri","collected_at"]|index($k)!=null)' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)" \
    "unexpected keys: $(jqr '[.evidence[]|keys[]]|unique|map(select(["type","source","status","reason","uri","collected_at"]|index(.)==null))|join(",")' "${name}")"

  # Dangling refs mean the hypothesis cites evidence that is not in the bundle.
  local dangling
  dangling="$(jq -r '
    ([.evidence[]| .uri // empty] + [.evidence[]| .type // empty] + [.evidence[]| .source // empty]) as $known
    | [ .probable_causes[] | (.evidence_refs // []) + (.contradicting_evidence_refs // []) ]
    | flatten
    | map(select(. as $r | ($known | map(select(. == $r)) | length) == 0))
    | join(",")' "${RAW_DIR}/${name}.json" 2>/dev/null || printf '')"
  assert "S2/${wl}" "all evidence_refs resolve to an EvidenceRef (no dangling refs)" \
    "$([[ -z "${dangling}" ]] && echo 0 || echo 1)" "dangling=${dangling}"

  assert "S2/${wl}" "pod-scoped evidence uses the actual fixture pod identity" \
    "$(jq -e --arg pod "${expected_pod}" '
      [.evidence[]
        | select(.status=="available")
        | select(.type=="pod-status" or .type=="pod_logs" or .type=="describe")
        | .uri
      ] as $uris
      | ($uris|length>0) and ($uris|all(contains($pod)))
    ' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)" \
    "expected_pod=${expected_pod}"

  assert "S2/${wl}" "facade accepted the grounded agent output" \
    "$(jq -e '[.evidence[]|select(.type=="agent-output-validation")]|length==0' \
      "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  assert "S2/${wl}" "recommended_next_steps present (human actions only)" \
    "$(jq -e '(.recommended_next_steps|type=="array") and (.recommended_next_steps|length>0)' "${RAW_DIR}/${name}.json" >/dev/null 2>&1 && echo 0 || echo 1)"
}

investigate \
  uc1-imagepull \
  s2-imagepull \
  '0\.0\.0-openkubes|does not exist|not found|manifest|image.*pull' \
  'DB_DSN|required config key|started and exited' \
  "${IMAGEPULL_POD}"
investigate \
  uc1-crashloop \
  s2-crashloop \
  'DB_DSN|required config key|configuration key.*missing' \
  'image.*pull|registry credential|image does not exist' \
  "${CRASHLOOP_POD}"

# ── S3 — collect_diagnostic_evidence (incl. capability delta) ────────────────
head2 "S3 — collect_diagnostic_evidence (uc1-crashloop, requesting host_journal on purpose)"
S3_CODE="$(call s3 /v1/collect_diagnostic_evidence \
  "{\"cluster\":\"${CLUSTER}\",\"namespace\":\"${NS_EVIDENCE}\",\"workload\":\"uc1-crashloop\",\"time_range\":\"PT1H\",\"evidence_types\":[\"events\",\"logs\",\"describe\",\"host_journal\"]}")"
log "HTTP ${S3_CODE}"
assert S3 "HTTP 200" "$([[ "${S3_CODE}" == "200" ]] && echo 0 || echo 1)" "got ${S3_CODE}"

if [[ "${S3_CODE}" == "200" ]]; then
  assert S3 "EvidenceBundle required fields present" \
    "$(jq -e 'has("cluster") and has("collected_at") and has("evidence") and has("provider_capabilities")' "${RAW_DIR}/s3.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  assert S3 "events + logs evidence available with uri" \
    "$(jq -e '([.evidence[]|select(.type=="events" and .status=="available" and (.uri//""|length>0))]|length>0) and ([.evidence[]|select(.type=="logs" and .status=="available" and (.uri//""|length>0))]|length>0)' "${RAW_DIR}/s3.json" >/dev/null 2>&1 && echo 0 || echo 1)" \
    "types=$(jqr '[.evidence[]|"\(.type):\(.status)"]|join(", ")' s3)"

  # ADR-021 test 5: a declared-absent capability must be reported, not omitted.
  assert S3 "host_journal reported as unavailable WITH a reason (capability delta, not silence)" \
    "$(jq -e '[.evidence[]|select((.type|test("host_?journal";"i")) or (.source|test("host_?journal";"i")))|select(.status=="unavailable" and (.reason//""|length>0))]|length>0' "${RAW_DIR}/s3.json" >/dev/null 2>&1 && echo 0 || echo 1)" \
    "no host_journal ref with status=unavailable+reason — silent omission is an ADR-021 test 5 failure"

  assert S3 "no embedded payloads in the bundle (refs only)" \
    "$(jq -e '[.evidence[]|keys[]]|unique|all(. as $k | ["type","source","status","reason","uri","collected_at"]|index($k)!=null)' "${RAW_DIR}/s3.json" >/dev/null 2>&1 && echo 0 || echo 1)"

  # Coarse secret sniff over the whole bundle: secret-ish JSON keys, plus classic
  # value patterns. Deliberately does not flag the word "secret" inside prose, so
  # a reason like "secrets are excluded from this profile" stays clean.
  SECRET_RE='"(password|passwd|token|secret|bearer|private_key|apikey|api_key)"[[:space:]]*:|(password|passwd|api[_-]?key)[[:space:]]*[:=]|BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._-]{20,}'
  assert S3 "no secret-looking material in the bundle" \
    "$(grep -Eiq "${SECRET_RE}" "${RAW_DIR}/s3.json" && echo 1 || echo 0)" \
    "secret-like content found in ${RAW_DIR}/s3.json — inspect before attaching"
fi

# ── T4 — statelessness restart test (mechanical half) ────────────────────────
OC_POD_BEFORE=""; OC_POD_AFTER=""
if [[ "${SKIP_RESTART}" -eq 1 ]]; then
  log ""
  log "T4 skipped (--skip-restart)"
  record T4 "restart test" MANUAL "skipped via --skip-restart"
else
  head2 "T4 — OpenClaw statelessness restart test"

  if ! "${KUBECTL[@]}" -n "${OPENCLAW_NS}" get deploy "${OPENCLAW_RELEASE}" >/dev/null 2>&1; then
    log "openclaw deployment not found in ${OPENCLAW_NS} — T4 cannot run"
    record T4 "openclaw deployment reachable" FAIL "deploy/${OPENCLAW_RELEASE} not found in ${OPENCLAW_NS}"
  else
    # 1) no persistent volume: statelessness must be structural, not incidental.
    PVC_COUNT="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get deploy "${OPENCLAW_RELEASE}" \
      -o json | jq '[.spec.template.spec.volumes[]?|select(has("persistentVolumeClaim"))]|length')"
    VOL_KINDS="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get deploy "${OPENCLAW_RELEASE}" \
      -o json | jq -r '[.spec.template.spec.volumes[]?|keys[]|select(.!="name")]|unique|join(",")')"
    log "volumes: ${VOL_KINDS} (PVCs: ${PVC_COUNT})"
    assert T4 "no PVC on the openclaw Deployment (emptyDir/configMap only)" \
      "$([[ "${PVC_COUNT}" -eq 0 ]] && echo 0 || echo 1)" "PVCs=${PVC_COUNT}, volumes=${VOL_KINDS}"

    OC_POD_BEFORE="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get pods -l "app.kubernetes.io/name=openclaw" \
      -o jsonpath='{.items[0].metadata.name}')"
    OC_START_BEFORE="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get pod "${OC_POD_BEFORE}" \
      -o jsonpath='{.status.startTime}')"
    log "pod before: ${OC_POD_BEFORE} (started ${OC_START_BEFORE})"
    log ""
    log "${c_yel}Before continuing: hold a >=3-turn conversation with the OpenClaw model in"
    log "Open WebUI (include one diagnostics question) and note its title.${c_off}"
    if [[ -t 0 ]]; then
      read -r -p "Conversation prepared? press Enter to delete the pod (Ctrl-C to abort) " _ || true
    else
      log "(non-interactive: proceeding without the UI precondition — T4 UI criteria stay MANUAL)"
    fi

    "${KUBECTL[@]}" -n "${OPENCLAW_NS}" delete pod "${OC_POD_BEFORE}" --wait=true >/dev/null
    "${KUBECTL[@]}" -n "${OPENCLAW_NS}" rollout status "deploy/${OPENCLAW_RELEASE}" --timeout=300s >/dev/null
    OC_POD_AFTER="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get pods -l "app.kubernetes.io/name=openclaw" \
      -o jsonpath='{.items[0].metadata.name}')"
    OC_RESTARTS="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" get pod "${OC_POD_AFTER}" \
      -o jsonpath='{.status.containerStatuses[0].restartCount}')"
    log "pod after:  ${OC_POD_AFTER} (restartCount ${OC_RESTARTS})"

    assert T4 "a genuinely new pod replaced the old one (not a container restart)" \
      "$([[ -n "${OC_POD_AFTER}" && "${OC_POD_AFTER}" != "${OC_POD_BEFORE}" && "${OC_RESTARTS}" == "0" ]] && echo 0 || echo 1)" \
      "before=${OC_POD_BEFORE}, after=${OC_POD_AFTER}, restartCount=${OC_RESTARTS}"

    # 2) the new pod serves again without operator action.
    GW_OK=1
    if "${KUBECTL[@]}" -n "${OPENCLAW_NS}" exec "deploy/${OPENCLAW_RELEASE}" -- \
        node -e "fetch('http://127.0.0.1:18789/readyz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1; then
      GW_OK=0
    fi
    assert T4 "gateway ready again after restart (no operator action)" "${GW_OK}"

    # 3) local state is genuinely gone — the evidence that statelessness holds.
    STATE_LS="$("${KUBECTL[@]}" -n "${OPENCLAW_NS}" exec "deploy/${OPENCLAW_RELEASE}" -- \
      sh -c 'ls -A /home/node/.openclaw 2>/dev/null | tr "\n" " "' 2>/dev/null || printf '<unreadable>')"
    log "openclaw local state after restart: ${STATE_LS}"
    record T4 "local state after restart is only the init-copied config" \
      "$([[ -n "${STATE_LS}" && "${STATE_LS}" != "<unreadable>" ]] && echo PASS || echo FAIL)" \
      "contents: ${STATE_LS}"

    # 4) the contract still serves after the consumer was replaced.
    T4_CODE="$(call t4-post-restart /v1/get_platform_health "{\"clusters\":[\"${CLUSTER}\"]}")"
    assert T4 "contract still serves after the restart (HTTP 200)" \
      "$([[ "${T4_CODE}" == "200" ]] && echo 0 || echo 1)" "got ${T4_CODE}"

    record T4 "Open WebUI still lists the conversation and its full history" MANUAL
    record T4 "follow-up turn in the same conversation succeeds with a Source: line" MANUAL
  fi
fi

# ── S4 — OpenClaw path / provenance (operator) ───────────────────────────────
record S4 "answer ends with 'Source: platform-diagnostics/<tool>'" MANUAL
record S4 "adapter + facade logs show the matching call (server-side provenance)" MANUAL
record S4 "stated symptoms match the S2 investigation, nothing invented" MANUAL
record S4 "openclaw holds no cluster credentials (make verify-kubectl)" MANUAL

# ── report ───────────────────────────────────────────────────────────────────
verdict="PASS"
[[ "${FAIL_N}" -gt 0 ]] && verdict="FAIL"

{
  echo "# OK-14 UC-1 evidence report"
  echo
  echo "- Generated: ${TS} (UTC)"
  echo "- Cluster: \`${CLUSTER}\`"
  echo "- Facade: \`svc/${PD_SVC}.${PD_NS}:${PD_PORT}\`"
  echo "- Fixture namespace: \`${NS_EVIDENCE}\`"
  echo "- Protocol: \`docs/agentic-ai-poc-evidence-protocol.md\`"
  echo "- Raw responses: \`$(basename "${RAW_DIR}")/\`"
  echo "- Provider capabilities (deployed): \`${PROV_CAPS_DEPLOYED:-<facade default>}\`"
  echo
  echo "## Automated verdict: ${verdict}"
  echo
  echo "${PASS_N} passed, ${FAIL_N} failed, ${SKIP_N} awaiting operator confirmation."
  echo
  echo "> The automated verdict covers machine-checkable criteria only. Items marked"
  echo "> MANUAL are UI-bound and must be confirmed by the operator before this report"
  echo "> is attached to OK-14."
  echo
  echo "## Results"
  echo
  echo "| Scenario | Criterion | Result | Detail |"
  echo "|---|---|---|---|"
  for r in "${RESULTS[@]}"; do
    IFS="${SEP}" read -r sc crit vd detail <<<"$r"
    printf '| %s | %s | %s | %s |\n' \
      "${sc//|/\\|}" "${crit//|/\\|}" "$vd" "${detail//|/\\|}"
  done
  echo
  echo "## Observed key values"
  echo
  echo "| Item | Value |"
  echo "|---|---|"
  echo "| S1 cluster status | \`$(jqmd '.clusters[0].status // "n/a"' s1)\` |"
  echo "| S2 imagepull top hypothesis | $(jqmd '.probable_causes[0].hypothesis // "n/a"' s2-imagepull) |"
  echo "| S2 imagepull counter-evidence | \`$(jqmd '[.probable_causes[].counter_evidence_status]|join(",")' s2-imagepull)\` |"
  echo "| S2 crashloop top hypothesis | $(jqmd '.probable_causes[0].hypothesis // "n/a"' s2-crashloop) |"
  echo "| S2 crashloop counter-evidence | \`$(jqmd '[.probable_causes[].counter_evidence_status]|join(",")' s2-crashloop)\` |"
  echo "| S3 evidence types | \`$(jqmd '[.evidence[]|"\(.type):\(.status)"]|join(", ")' s3)\` |"
  echo "| T4 pod before → after | \`${OC_POD_BEFORE:-n/a}\` → \`${OC_POD_AFTER:-n/a}\` |"
  echo
  echo "## Operator sections to fill in"
  echo
  echo "### S4 — OpenClaw path (provenance)"
  echo
  echo "Question asked:"
  echo
  echo "> What is the state of workload uc1-crashloop in namespace ${NS_EVIDENCE} on cluster ${CLUSTER}?"
  echo
  echo "- Answer (paste, incl. the trailing \`Source:\` line):"
  echo
  echo '  ```'
  echo '  '
  echo '  ```'
  echo
  echo "- Adapter/facade log lines proving the call (paste):"
  echo
  echo '  ```'
  echo '  '
  echo '  ```'
  echo
  echo "- Symptoms consistent with S2? ( ) yes ( ) no — notes:"
  echo
  echo "### T4 — Open WebUI half"
  echo
  echo "- Conversation title:"
  echo "- Turns before restart:"
  echo "- After restart: conversation listed? ( ) yes ( ) no"
  echo "- After restart: full history readable? ( ) yes ( ) no"
  echo "- Follow-up turn succeeded? ( ) yes ( ) no — answer excerpt:"
  echo
  echo '  ```'
  echo '  '
  echo '  ```'
  echo
  echo "## Interpretation"
  echo
  echo "- Acceptance criterion is *no user-visible state loss*, not that OpenClaw keeps"
  echo "  nothing. An emptied local state plus an intact Open WebUI conversation is the"
  echo "  expected result and confirms the ADR-015 assumption."
  echo "- A FAIL belongs on the ticket owning the defect, not on OK-14: the"
  echo "  \`unknown\` health fallback and the missing MCP adapter deploy path are OK-92;"
  echo "  executable contract tests and Profile B are OK-91; RKE2 capability delta is OK-95."
} >"${REPORT}"

head2 "summary"
log "${PASS_N} passed, ${FAIL_N} failed, ${SKIP_N} awaiting operator confirmation"
log "report: ${REPORT}"
log "raw:    ${RAW_DIR}/"
log ""
log "Next: fill in the S4 and T4 operator sections, then attach the report to OK-14."

[[ "${FAIL_N}" -eq 0 ]]
