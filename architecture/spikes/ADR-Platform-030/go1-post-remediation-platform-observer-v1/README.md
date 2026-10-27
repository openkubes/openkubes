# OK-141 post-remediation Platform observer v1

This read-only observer follows the successful registration audience remediation.
It polls only the three bound Argo Applications on `ok-shared` and stops when all
three report the exact expected revision, `Synced` and `Healthy`, or after ten
minutes. It does not read Secrets, contact the target directly, mutate resources,
run the capability test or retry any earlier Happy-Run stage.
