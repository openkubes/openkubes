#!/usr/bin/env bash
# Functional capability probe -> emits a CapabilityVerified artifact (ADR-Platform-032 §13 bound 4).
#
# Proves the requested capability by EXERCISING it, and emits typed evidence. Deliberately
# never reads .status.pgDataImageInfo.extensions: CNPG reported pgvector as configured there
# on a cluster where the extension could not be created, so the operator restating its own
# input is not evidence of function.
#
# Everything the artifact binds is READ FROM THE CLUSTER, never passed as an argument:
#   clusterRef.uid   <- the CNPG Cluster object
#   delivery.imageDigest <- pod containerStatuses[].imageID. NOT spec.imageName and NOT
#                       status.pgDataImageInfo.image: both are tag-only here, and a tag can
#                       be re-pushed under a proof that still looks valid.
#   databaseRef      <- annotation stamped by the composer (see FAIL-CLOSED below)
#
# FAIL-CLOSED: if the composed Database binding is absent, the artifact is emitted WITHOUT
# databaseRef so the API server refuses it. A probe run on a standalone cluster evidences the
# MECHANISM, never delivered capability for a composed Database. Passing the uid in by hand
# is exactly the substitution bound 4 exists to prevent.
#
# Non-destructive: all DDL runs inside a transaction that is rolled back.
#
# Usage: capability-probe-v2.sh <namespace> <cnpg-cluster> [capability]
# Exit:  0 = Valid, 1 = Failed, 2 = usage/plumbing error
set -uo pipefail

NS="${1:?namespace required}"
CLUSTER="${2:?cnpg cluster required}"
CAP="${3:-pgvector}"

DB_UID_ANNOTATION="platform.openkubes.ai/database-uid"
DB_NAME_ANNOTATION="platform.openkubes.ai/database-name"

case "$CAP" in
  pgvector)        EXT=vector; COL='vector(3)'; LIT_A='[1,2,3]'; LIT_B='[4,5,6]'; LIT_C='[1,2,4]'
                   CAP_NAME='postgresql.extension.pgvector' ;;
  # Control: contrib's cube implements the same <-> operator and ships in the minimal image,
  # so it drives the identical code path and proves verdict=Valid is reachable. Without it a
  # probe that can only ever report Failed would look correct.
  __selftest-cube) EXT=cube;   COL='cube';      LIT_A='(1,2,3)'; LIT_B='(4,5,6)'; LIT_C='(1,2,4)'
                   CAP_NAME='postgresql.extension.__selftest-cube' ;;
  *) echo "verdict=Failed reason=UnknownCapability capability=$CAP" >&2; exit 2 ;;
esac

PRIMARY="$(kubectl -n "$NS" get cluster "$CLUSTER" -o jsonpath='{.status.currentPrimary}' 2>/dev/null)"
[ -n "$PRIMARY" ] || { echo "verdict=Failed reason=NoPrimaryFound cluster=$CLUSTER" >&2; exit 2; }

CLUSTER_UID="$(kubectl -n "$NS" get cluster "$CLUSTER" -o jsonpath='{.metadata.uid}' 2>/dev/null)"
IMAGE_NAME="$(kubectl -n "$NS" get pod "$PRIMARY" -o jsonpath='{.spec.containers[?(@.name=="postgres")].image}' 2>/dev/null)"
IMAGE_DIGEST="$(kubectl -n "$NS" get pod "$PRIMARY" -o jsonpath='{range .status.containerStatuses[?(@.name=="postgres")]}{.imageID}{end}' 2>/dev/null | sed 's/.*@//')"
DB_UID="$(kubectl -n "$NS" get cluster "$CLUSTER" -o jsonpath="{.metadata.annotations.${DB_UID_ANNOTATION//./\\.}}" 2>/dev/null)"
DB_NAME="$(kubectl -n "$NS" get cluster "$CLUSTER" -o jsonpath="{.metadata.annotations.${DB_NAME_ANNOTATION//./\\.}}" 2>/dev/null)"

psql_q() {
  kubectl -n "$NS" exec "$PRIMARY" -c postgres -- psql -U postgres -X -v ON_ERROR_STOP=1 -tAc "$1" 2>&1
}

START=$(date -u +%s)

# check 1 — catalog presence. Passes on an extension that cannot be created, so it is
# necessary but never sufficient.
CATALOG_VERSION="$(psql_q "SELECT default_version FROM pg_available_extensions WHERE name='${EXT}';" | tr -d '[:space:]')"
if [ -z "$CATALOG_VERSION" ]; then
  echo "verdict=Failed reason=RequestedCapabilityAbsent capability=${CAP} extension=${EXT} detail=not-in-pg_available_extensions" >&2
  exit 1
fi

# checks 2-4 — functional exercise, rolled back. Creation alone passes on a loadable-but-broken
# operator, and ordering alone passes on a stub returning a constant, so the DISTANCE VALUE is
# captured too and compared against an independently computed expectation.
OUT="$(psql_q "
BEGIN;
CREATE EXTENSION IF NOT EXISTS ${EXT};
SELECT 'PROBE_EXTVER='||extversion FROM pg_extension WHERE extname='${EXT}';
CREATE TEMP TABLE _probe (id int, v ${COL}) ON COMMIT DROP;
INSERT INTO _probe VALUES (1,'${LIT_A}'),(2,'${LIT_B}'),(3,'${LIT_C}');
SELECT 'PROBE_ORDER='||string_agg(id::text, ',' ORDER BY d) FROM (
  SELECT id, v <-> '${LIT_A}' AS d FROM _probe) s;
SELECT 'PROBE_NEAREST='||id FROM _probe ORDER BY v <-> '${LIT_A}' LIMIT 1;
SELECT 'PROBE_FARTHEST='||(v <-> '${LIT_A}')::text FROM _probe ORDER BY v <-> '${LIT_A}' DESC LIMIT 1;
ROLLBACK;
")"

# psql interleaves command tags (BEGIN/CREATE EXTENSION/ROLLBACK) with result rows, so results
# must be pulled out BY MARKER. Reading the last line instead picks up ROLLBACK and fails a
# capability that actually works.
mark() { printf '%s\n' "$OUT" | sed -n "s/^$1=//p" | tr -d '\r'; }
EXTVER="$(mark PROBE_EXTVER   | tr -d '[:space:]')"
ORDERED="$(mark PROBE_ORDER   | tr -d '[:space:]')"
NEAREST="$(mark PROBE_NEAREST | tr -d '[:space:]')"
FARTHEST="$(mark PROBE_FARTHEST | tr -d '[:space:]')"

EXPECTED_FARTHEST="$(python3 -c "
import sys
a=[float(x) for x in '${LIT_A}'.strip('[]()').split(',')]
b=[float(x) for x in '${LIT_B}'.strip('[]()').split(',')]
print(repr(sum((x-y)**2 for x,y in zip(a,b))**0.5))
" 2>/dev/null)"

# check 5 — residue. Side-effect-freeness is what lets the same probe run against a live
# primary AND a recovery-verification pod without interfering, which is what keeps
# CapabilityConformant and RecoveryAssured independent conditions rather than a pipeline.
EXTS_AFTER="$(psql_q "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension;" | tr -d '[:space:]')"
PROBE_TABLES="$(psql_q "SELECT count(*) FROM pg_tables WHERE tablename LIKE '%probe%';" | tr -d '[:space:]')"

END=$(date -u +%s); DUR=$((END-START))
COMPLETED_AT="$(date -u -d "@${END}" +%Y-%m-%dT%H:%M:%SZ)"
PROBE_DIGEST="sha256:$(sha256sum "$0" | awk '{print $1}')"
PG_MAJOR="$(psql_q "SHOW server_version_num;" | tr -d '[:space:]' | cut -c1-2)"

FAILED=""
[ -n "$EXTVER" ]                            || FAILED="extension-created"
[ "$NEAREST" = "1" ]                        || FAILED="${FAILED:-operator-orders-by-distance}"
[ "$ORDERED" = "1,3,2" ]                    || FAILED="${FAILED:-operator-orders-by-distance}"
[ "$FARTHEST" = "$EXPECTED_FARTHEST" ]      || FAILED="${FAILED:-operator-returns-true-distance}"
[ "$EXTS_AFTER" = "plpgsql" ]               || FAILED="${FAILED:-probe-left-no-residue}"
[ "$PROBE_TABLES" = "0" ]                   || FAILED="${FAILED:-probe-left-no-residue}"

if [ -n "$FAILED" ]; then
  echo "verdict=Failed reason=CapabilityNotFunctional capability=${CAP} failedCheck=${FAILED} extver=${EXTVER:-none} nearest=${NEAREST:-none} ordered=${ORDERED:-none} farthest=${FARTHEST:-none} expected=${EXPECTED_FARTHEST} extsAfter=${EXTS_AFTER} probeTables=${PROBE_TABLES}" >&2
  exit 1
fi

ART_NAME="$(printf '%s-%s' "$CLUSTER" "$(date -u -d "@${END}" +%Y%m%dt%H%M%Sz)")"

cat <<YAML
apiVersion: evidence.platform.openkubes.ai/v1alpha1
kind: CapabilityVerified
metadata:
  name: ${ART_NAME}
spec:
  capability:
    name: ${CAP_NAME}
    observedVersion: "${EXTVER}"
$(if [ -n "$DB_UID" ]; then cat <<REF
  databaseRef:
    apiVersion: platform.openkubes.ai/v1alpha1
    kind: Database
    name: ${DB_NAME}
    uid: ${DB_UID}
REF
else cat <<NOREF
  # databaseRef OMITTED — no ${DB_UID_ANNOTATION} annotation on the composed Cluster, so no
  # authentic binding to a Database exists. The API server will refuse this artifact, which is
  # correct: this run evidences the MECHANISM, not delivered capability for a composed Database.
NOREF
fi)
  clusterRef:
    apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    namespace: ${NS}
    name: ${CLUSTER}
    uid: ${CLUSTER_UID}
  delivery:
    mechanism: BundledImage
    imageName: ${IMAGE_NAME}
    imageDigest: ${IMAGE_DIGEST}
  checks:
    - name: catalog-lists-extension
      observed:
        catalogDefaultVersion: "${CATALOG_VERSION}"
    - name: extension-created
      observed:
        extensionVersion: "${EXTVER}"
    - name: operator-orders-by-distance
      observed:
        nearestId: ${NEAREST}
        orderedIds: [${ORDERED}]
    - name: operator-returns-true-distance
      observed:
        farthestDistance: "${FARTHEST}"
        expectedFarthestDistance: "${EXPECTED_FARTHEST}"
    - name: probe-left-no-residue
      observed:
        extensionsAfterRollback: [${EXTS_AFTER}]
        probeTablesRemaining: ${PROBE_TABLES}
  timing:
    completedAt: "${COMPLETED_AT}"
    duration: PT${DUR}S
  probeDigest: ${PROBE_DIGEST}
  verifierVersion: pgvector-probe/0.2.0
  postgresMajorVersion: ${PG_MAJOR}
YAML
exit 0
