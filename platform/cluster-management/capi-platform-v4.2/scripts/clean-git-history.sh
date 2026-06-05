#!/usr/bin/env bash
# clean-git-history.sh
#
# Removes sensitive data from Git history using git-filter-repo.
# Prerequisite: git-filter-repo installed
#   brew install git-filter-repo   # macOS
#   pip install git-filter-repo    # alternatively
#
# WARNING: This script rewrites the entire Git history.
# A force-push is required afterwards: git push --force
# All collaborators must re-clone the repository.
#
# Usage:
#   bash scripts/clean-git-history.sh <IP_TO_REMOVE> [<IP_TO_REMOVE> ...]
#
# Example:
#   bash scripts/clean-git-history.sh 1.2.3.4 5.6.7.8

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: bash scripts/clean-git-history.sh <IP_TO_REMOVE> [<IP_TO_REMOVE> ...]"
  echo "Example: bash scripts/clean-git-history.sh 1.2.3.4"
  exit 1
fi

echo "Checking for git-filter-repo..."
if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "ERROR: git-filter-repo not found."
  echo "Install with: brew install git-filter-repo"
  exit 1
fi

echo "Patterns to remove from history:"
for ip in "$@"; do
  echo "  - ${ip} --> <CONTROL_PLANE_ENDPOINT_IP>"
done
echo "  - KUBEVIRT_VM_NAMESPACE=\"capi-workload\" --> <set-at-runtime>"
echo ""
printf "Continue? (yes/no): "
read -r confirm
if [ "${confirm}" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

PATTERNS_FILE="$(mktemp)"

# Add IP patterns from arguments
for ip in "$@"; do
  echo "${ip}==><CONTROL_PLANE_ENDPOINT_IP>" >> "${PATTERNS_FILE}"
done

# Add static patterns
cat >> "${PATTERNS_FILE}" << 'PATTERNS'
KUBEVIRT_VM_NAMESPACE="capi-workload"==>KUBEVIRT_VM_NAMESPACE="<set-at-runtime>"
export KUBEVIRT_VM_NAMESPACE="capi-workload"==>export KUBEVIRT_VM_NAMESPACE="<set-at-runtime>"
PATTERNS

git filter-repo --force --replace-text "${PATTERNS_FILE}"
rm -f "${PATTERNS_FILE}"

echo ""
echo "Done. History rewritten."
echo ""
echo "Next steps:"
echo "  1. Review: git log -p | grep -E 'ENDPOINT_IP|KUBEVIRT'"
echo "  2. Force-push: git push --force"
echo "  3. All collaborators must re-clone the repository."
