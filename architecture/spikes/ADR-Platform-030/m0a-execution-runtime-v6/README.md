# OK-141 M0a v6 runtime and rollback result

Status: **STOP-NOT-SUCCESS / exact rollback complete / grants consumed**

The single v6 create-only submission left four cluster-scoped CAAPH API
objects. The corrected token probe independently proved rejection after the
bound time. No retry or automatic rollback occurred.

A separately authorized, UID-bound rollback deleted exactly those four
objects. A fresh read-only preflight then proved all 19 reviewed identities
absent, no temporary bootstrap state, and zero CAPI lifecycle objects.

The raw execution and rollback evidence remain local. This directory is a
redacted local checkpoint and grants no publication or forward execution.
