# OK-141 Platform convergence diagnostic v1

The runtime-bound Happy Run submitted the exact Platform projection, but the
three Argo CD Applications did not all reach the bound immutable revision with
both `Synced` and `Healthy` inside the 45-minute observer budget.

This candidate permits exactly three read-only Application GETs on `ok-shared`.
It records only revision/status fields, categorized condition-message digests
and aggregate resource states. It excludes raw Application objects, condition
messages, Secrets, Pods, logs, target-cluster access and all mutation.

The failed Happy Run is consumed and cannot be resumed or retried through this
diagnostic. The candidate remains `NO-GO` until a separate exact grant exists.
