# OK-141 delete D0 DataVolume-filter amendment v2

Status: **OFFLINE-AMENDED / EXPLICIT NEW READ GRANT REQUIRED / NO-GO**

D0-v1 stopped fail-closed before writing private output because its DataVolume
query expected two objects selected by `cluster.x-k8s.io/cluster-name`, but the
query returned zero. The rendered KubeVirt templates define the two boot
DataVolume names under each VirtualMachine `spec.dataVolumeTemplates`; they do
not declare that CAPI label on the DataVolume metadata.

V2 therefore keeps the other 35 queries byte-for-byte equivalent and replaces
only the DataVolume selection rule:

```text
two bound VirtualMachines
        ↓
derive exactly two spec.dataVolumeTemplates[*].metadata.name values
        ↓
namespace-bounded DataVolume collection
        ↓
retain only those exact two names
```

The historical v1 candidate, grant and stopped attempt remain unchanged. V2
uses new private output paths and requires a new single-use grant. It grants no
delete, cleanup, retry, mutation, outage or failure-injection authority.
