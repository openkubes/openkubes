# OK-141 M0a v7.1 runtime result

Status: **STOP-NOT-SUCCESS / CAAPH partial state retained / grants consumed**

The single v7.1 split-authority run created all 19 reviewed CAAPH objects, but
the controller did not become ready. Three controller arguments retained
Cluster API provider variable syntax literally. Kubernetes does not execute a
shell for container arguments, and the controller rejected the literal Boolean
value before starting.

The seven temporary credential and admission objects were removed. The
short-lived TokenRequest credential was rejected after its bound expiration
boundary. No retry or automatic rollback occurred.

The raw execution evidence remains local. This directory is a redacted local
checkpoint and grants no publication, repair, retry, rollback, target
convergence, or forward execution authority.
