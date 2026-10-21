# OpenKubes Agent Contract v1alpha1

This contract is the read-only producer boundary for Console Agent catalog and
deployment evidence. A Pod is not an AgentDeployment. Producers must expose an
immutable artifact digest, signature/provenance references, and correlated
deployment evidence before a consumer may mark an Agent `Verified`.

The contract is descriptive in this first step; no Kubernetes watcher or API
endpoint is enabled by this document.
