# OK-141 Platform SSA resume v2

This resume follows the zero-write preflight closure caused by the temporary
`ok-mgmt` outage.  It does not reuse either the expired registration token or
the consumed live amendment candidate.

Execution order is fixed:

1. verify the fresh registration-token candidate;
2. issue one 10800-second default-audience token and replace the exact Argo
   registration Secret with optimistic concurrency;
3. verify the fresh SSA amendment candidate;
4. repeat all 13 exact preflight reads;
5. only if all identities still match, replace the 13 bound objects and add
   `ServerSideApply=true` only to the Core Application;
6. observe the three Applications without an explicit sync.

The prior lifecycle, Cilium, NetworkReady and Runtime-Binding stages are not
repeated.  Failure remains `STOP-PRESERVE-NO-RETRY`.
