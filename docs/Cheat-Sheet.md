# OpenKubes Operations Cheat Sheet

Quick reference for day-to-day platform operations.

---

## Cluster Lifecycle

### Deploy a cluster

```bash
# Edit examples/ok1.yaml and set your desired parameters
kubectl apply -f platform/cluster-management/crossplane/examples/ok1.yaml

# Watch the deploy Job
kubectl get jobs -n openkubes-system -w

# Follow logs
kubectl logs -n openkubes-system \
  $(kubectl get pods -n openkubes-system | grep deploy | grep Running | awk '{print $1}') -f
```

### Get workload cluster kubeconfig

```bash
# Replace ok1-gh5ms with your actual XR name
clusterctl get kubeconfig ok1-gh5ms -n ok1-gh5ms \
  --kubeconfig ~/.kube/ok-capi-kubevirt-on-kbm.yaml \
  > ~/.kube/ok1-gh5ms.kubeconfig

KUBECONFIG=~/.kube/ok1-gh5ms.kubeconfig kubectl get nodes
```

### Clean up a cluster (self-service)

```bash
# Edit examples/cleanup-ok1.yaml and set clusterName to the actual XR name
# Find the XR name with: kubectl get cluster -A
kubectl apply -f platform/cluster-management/crossplane/examples/cleanup-ok1.yaml

# Watch the cleanup Job
kubectl get jobs -n openkubes-system -w

# After cleanup is done, delete both claims
kubectl delete -f platform/cluster-management/crossplane/examples/ok1.yaml
kubectl delete -f platform/cluster-management/crossplane/examples/cleanup-ok1.yaml
```

### Check cluster status

```bash
kubectl get cluster -A
kubectl get machines -A
kubectl get kubevirtmachine -A
```

---

## Debugging

### Follow deploy Job logs

```bash
kubectl logs -n openkubes-system job/deploy-ok1-gh5ms -f
```

### Check XR status and events

```bash
# Get XR name
kubectl get kubevirtcluster.platform.openkubes.ai

# Describe XR
kubectl describe kubevirtcluster.platform.openkubes.ai <xr-name> | tail -20
```

### Check composed Objects

```bash
XR=ok1-gh5ms
kubectl get objects.kubernetes.crossplane.io \
  -l crossplane.io/composite=${XR}
```

### Re-trigger XR reconciliation

```bash
kubectl annotate kubevirtcluster.platform.openkubes.ai <xr-name> \
  reconcile.crossplane.io/triggered="$(date +%s)" --overwrite
```

### Check Crossplane functions

```bash
kubectl get functions.pkg.crossplane.io
kubectl get providers.pkg.crossplane.io
```

### Check active composition revision

```bash
kubectl get compositionrevision | grep kubevirtcluster
kubectl get composition kubevirtcluster.platform.openkubes.ai \
  -o jsonpath='{.status.currentRevision}'
```

---

## Force Cleanup (Emergency)

Use when the self-service cleanup fails or resources are stuck in `Terminating`.

### Remove CAPI finalizers and delete namespace

```bash
# Replace <namespace> with the stuck namespace, e.g. ok1-gh5ms
NAMESPACE=ok1-gh5ms

for kind in kubevirtmachine machine machineset machinedeployment \
            kubeadmcontrolplane kubevirtcluster; do
  kubectl get "${kind}" -n "${NAMESPACE}" -o name 2>/dev/null | \
    xargs -I {} kubectl patch {} -n "${NAMESPACE}" \
      --type=merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
done

kubectl delete ns "${NAMESPACE}" --ignore-not-found

or:

kubectl patch namespace ok1 \
  --type=merge -p '{"spec":{"finalizers":[]}}'

or:

# Namespace force-delete
kubectl get namespace ok1 -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); d['spec']['finalizers']=[]; print(json.dumps(d))" | \
  kubectl replace --raw /api/v1/namespaces/ok1/finalize -f -# Namespace force-delete
kubectl get namespace ok1 -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); d['spec']['finalizers']=[]; print(json.dumps(d))" | \
  kubectl replace --raw /api/v1/namespaces/ok1/finalize -f -

# Finalizer von allen CAPI-Objekten in ok1 entfernen
for kind in kubevirtmachine machine machineset machinedeployment \
            kubeadmcontrolplane kubevirtcluster; do
  kubectl get "${kind}" -n ok1 -o name 2>/dev/null | \
    xargs -I {} kubectl patch {} -n ok1 \
      --type=merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
done
```

### Force-delete multiple stuck namespaces

```bash
for ns in ok1-abc12 ok1-def34; do
  for kind in kubevirtmachine machine machineset machinedeployment \
              kubeadmcontrolplane kubevirtcluster; do
    kubectl get "${kind}" -n "${ns}" -o name 2>/dev/null | \
      xargs -I {} kubectl patch {} -n "${ns}" \
        --type=merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
  done
  kubectl delete ns "${ns}" --ignore-not-found
done
```

### Delete stuck VMs on Infra Cluster

```bash
# Switch to infra cluster
kbm

# List all VMs
kubectl get vm -A

# Delete stuck VM
kubectl -n <namespace> delete vm <vm-name>
kubectl -n <namespace> delete vmi <vmi-name>
```

### Force-delete stuck XR

```bash
kubectl patch kubevirtcluster.platform.openkubes.ai <xr-name> \
  --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]'
```

---

## Image Management

### Build and push runner image

```bash
cd platform/cluster-management/capi-platform-v4.2

docker build --no-cache \
  -t kubernautslabs/capi-platform-runner:v4.2 \
  -f runner/Dockerfile .

# Verify scripts are in the image
docker run --rm kubernautslabs/capi-platform-runner:v4.2 \
  ls /workspace/scripts/

docker push kubernautslabs/capi-platform-runner:v4.2
```

### Clear image cache on Management Cluster nodes

```bash
for ip in <MGMT_VM_1_IP> <MGMT_VM_2_IP> <MGMT_VM_3_IP>; do
  ssh ubuntu@${ip} \
    "sudo crictl rmi kubernautslabs/capi-platform-runner:v4.2 2>/dev/null || true"
done
```

### Verify image content

```bash
# Check scripts
docker run --rm kubernautslabs/capi-platform-runner:v4.2 \
  ls /workspace/scripts/

# Check specific file
docker run --rm kubernautslabs/capi-platform-runner:v4.2 \
  grep -n "base_ns" /workspace/scripts/deploy-full.sh

# Check Makefile targets
docker run --rm kubernautslabs/capi-platform-runner:v4.2 \
  grep -c "INFRA_CLUSTER_SECRET_NAMESPACE" /workspace/Makefile
```

---

## Crossplane Operations

### Apply full Crossplane stack

```bash
cd platform/cluster-management/crossplane

kubectl apply -f namespace.yaml
kubectl apply -f rbac.yaml
kubectl apply -f xrd.yaml
kubectl apply -f xrd-cleanup.yaml
kubectl apply -f composition.yaml
kubectl apply -f composition-cleanup.yaml
```

### Reinstall Composition (force new revision)

```bash
kubectl delete composition kubevirtcluster.platform.openkubes.ai
sleep 3
kubectl apply -f platform/cluster-management/crossplane/composition.yaml
```

### Check if Composition Resources are stored correctly

```bash
kubectl get composition kubevirtcluster.platform.openkubes.ai \
  -o json | jq '.spec.pipeline[0].input.resources | length'
# Expected: 2
```

### Install / upgrade functions

```bash
# function-patch-and-transform (Crossplane v2 compatible)
kubectl patch function function-patch-and-transform \
  --type=merge \
  -p '{"spec":{"package":"xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.10.1"}}'

# function-go-templating
kubectl apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-go-templating
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.11.4
EOF

kubectl get functions.pkg.crossplane.io -w
```

---

## Infra Cluster Operations

### Check Management VMs

```bash
# On Infra Cluster
kubectl get vm -n kubevirt -o wide
kubectl get vmi -n kubevirt -o wide
kubectl get svc -n kubevirt | grep -E "ok[0-9]-svc"
```

### Check workload VMs (per cluster namespace)

```bash
kubectl get vm -n ok1-gh5ms
kubectl get vmi -n ok1-gh5ms -o wide
```

### Access Management VM console

```bash
kubectl virt console ok1-vm -n kubevirt
# Exit: Ctrl+]
```
