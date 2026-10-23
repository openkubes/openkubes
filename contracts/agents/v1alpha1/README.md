# OpenKubes Agent Contract v1alpha1

This contract is the read-only producer boundary for Console Agent catalog and
deployment evidence. A Pod is not an AgentDeployment. Producers must expose an
immutable artifact digest, signature/provenance references, and correlated
deployment evidence before a consumer may mark an Agent `Verified`.

The contract is descriptive in this first step; no Kubernetes watcher or API
endpoint is enabled by this document.

## Registration and placement flow

The first implementation must keep registration, authorization, execution, and
observation separate:

1. A registry publishes an `AgentDefinition` containing the immutable image
   digest, signature and provenance references, declared tools, and required
   capabilities.
2. The Console creates an `AgentDeploymentClaim` only after reviewing the exact
   definition and a conformant target Worker Cluster. The claim binds the
   agent id, version, digest, target cluster, namespace, tools, and authority.
3. A cluster-side controller may execute the claim only once, and must reject a
   changed digest, unknown capability, expired grant, or mismatched target.
4. The controller publishes an `AgentDeployment` observation with the applied
   digest, namespace, readiness, observed generation, and an immutable evidence
   reference correlated to the claim.

The producer must never infer deployment from a Pod alone. Until the claim and
correlated evidence are present, the Console must show zero deployments and
must not offer an approved placement.
