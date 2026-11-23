#!/bin/sh
# Linux Bubblewrap gate: no unconfined fallback. Experimental, not production certification.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "${1-}" in
  '') PROGRAM=offline_assessor.py ;;
  --probe) PROGRAM=isolation_probe.py ;;
  *) echo 'ERROR: unsupported sandbox mode' >&2; exit 2 ;;
esac
for required in bwrap timeout; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "ERROR: sandbox requirement unavailable: $required; refusing unisolated execution" >&2
    exit 78
  fi
done
if [ "$(uname -s)" != Linux ]; then
  echo 'ERROR: Bubblewrap sandbox supported only on Linux' >&2
  exit 78
fi
# Rootless user, mount, PID and network namespaces. No /home, /etc, or host /mnt bind.
# Read-only runtime binds are needed for the system Python interpreter and libraries.
# If user namespaces are unavailable bwrap fails; this wrapper never falls back.
set -- --unshare-all --die-with-parent --new-session --clearenv \
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PYTHONNOUSERSITE 1 \
  --setenv PATH /usr/bin:/bin \
  --ro-bind /usr /usr --dir /work \
  --ro-bind "$HERE/$PROGRAM" "/work/$PROGRAM" \
  --proc /proc --dev /dev --chdir /work
for dir in /bin /lib /lib64; do
  if [ -e "$dir" ]; then
    set -- "$@" --ro-bind "$dir" "$dir"
  fi
done
# Namespace/mount failure is fatal; the payload never executes outside Bubblewrap.
timeout -k 1s 5s bwrap "$@" -- /usr/bin/python3 "/work/$PROGRAM"
