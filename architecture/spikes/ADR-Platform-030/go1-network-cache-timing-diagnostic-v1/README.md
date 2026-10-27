# OK-141 Cilium cached-health timing diagnostic v1

The corrected status semantics passed, but Resume v5 stopped because at least
one successful cached path exceeded the historical fixed 120-second age limit.

At the fixture-bound Cilium commit, the hidden `--probe` CLI flag invokes the
`PUT /status/probe` API, while that handler calls `FetchStatusResponse()`. The
server implementation returns `GetStatusResponse()` without starting a new
probe cycle. Separately, periodic results are exposed to the API on a
60-second ticker. Therefore command success does not imply that every returned
path was probed within a fixed 120-second window.

This one-shot candidate records only non-sensitive timing metadata:

- the advertised probe interval in seconds;
- response timestamp age;
- minimum and maximum successful path age;
- a sorted vector of the eight path ages;
- counts of successful, failed, or invalid status representations.

It retains no IP address, node name, raw status, raw probe output, Secret, or
Kubeconfig. It grants no retry, Happy Run continuation, mutation, cleanup, or
publication.

