# Finalizer entfernen und Namespaces löschen
for ns in ok1-6snf2 ok1-wk757; do
  for kind in kubevirtmachine machine machineset machinedeployment \
              kubeadmcontrolplane kubevirtcluster; do
    kubectl get "${kind}" -n "${ns}" -o name 2>/dev/null | \
      xargs -I {} kubectl patch {} -n "${ns}" \
        --type=merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
  done
  kubectl delete ns "${ns}" --ignore-not-found
done

# Prüfen
kubectl get cluster -A

