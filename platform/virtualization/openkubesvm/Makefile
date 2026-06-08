SHELL := /bin/bash
.DEFAULT_GOAL := help

vm                ?=
namespace         ?= openkubes-system
kubevirt_ns       ?= kubevirt
examples_dir      ?= examples
crossplane_dir    ?= crossplane

.PHONY: help vm-create vm-delete vm-status vm-ssh vm-apply vm-remove vm-list

help:
	@echo ""
	@echo "OpenKubesVM – VM Operations"
	@echo ""
	@echo "Setup (one-time):"
	@echo "  make setup                    Apply XRD + Composition to management cluster"
	@echo ""
	@echo "Via Crossplane (declarative):"
	@echo "  make vm-create  vm=ok4        Create VM via Crossplane Claim"
	@echo "  make vm-delete  vm=ok4        Delete VM via Crossplane Claim"
	@echo "  make vm-status  vm=ok4        Show VM claim + infra status"
	@echo ""
	@echo "Direct KubeVirt (lab):"
	@echo "  make vm-apply   vm=ok4        Apply VM directly on infra cluster"
	@echo "  make vm-remove  vm=ok4        Remove VM directly from infra cluster"
	@echo ""
	@echo "Utilities:"
	@echo "  make vm-list                  List all OpenKubesVMs"
	@echo "  make vm-ssh     vm=ok4        SSH into VM (reads IP from claim)"
	@echo ""

# ---------------------------------------------------------------
# Setup – apply XRD and Composition (one-time)
# ---------------------------------------------------------------
setup:
	@echo "[setup] applying OpenKubesVM Crossplane stack..."
	kubectl apply -k $(crossplane_dir)
	@echo "[setup] done ✅"
	@echo ""
	kubectl get xrd | grep openkubesvm || true
	kubectl get composition | grep openkubesvm || true

# ---------------------------------------------------------------
# VM Create – apply Crossplane Claim
# ---------------------------------------------------------------
vm-create:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-create vm=ok4"; exit 1)
	@test -f "$(examples_dir)/claims/$(vm)-openkubesvmclaim.yaml" || \
	  (echo "ERROR: $(examples_dir)/claims/$(vm)-openkubesvmclaim.yaml not found"; exit 1)
	@echo "[vm-create] creating VM '$(vm)' via Crossplane..."
	kubectl apply -f "$(examples_dir)/claims/$(vm)-openkubesvmclaim.yaml"
	@echo "[vm-create] waiting for VM to become Ready..."
	@for i in $$(seq 1 60); do \
	  READY=$$(kubectl get openkubesvmclaim "$(vm)" -n $(namespace) \
	    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo ""); \
	  SYNCED=$$(kubectl get openkubesvmclaim "$(vm)" -n $(namespace) \
	    -o jsonpath='{.status.conditions[?(@.type=="Synced")].status}' 2>/dev/null || echo ""); \
	  echo "[vm-create] SYNCED=$$SYNCED READY=$$READY ($$i/60)"; \
	  if [ "$$READY" = "True" ]; then \
	    echo "[vm-create] VM '$(vm)' is Ready ✅"; \
	    break; \
	  fi; \
	  [ "$$i" = "60" ] && echo "[vm-create] WARNING: timeout — check: make vm-status vm=$(vm)"; \
	  sleep 10; \
	done

# ---------------------------------------------------------------
# VM Delete – delete Crossplane Claim
# ---------------------------------------------------------------
vm-delete:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-delete vm=ok4"; exit 1)
	@echo "[vm-delete] deleting VM '$(vm)' via Crossplane..."
	kubectl delete openkubesvmclaim "$(vm)" -n $(namespace) --ignore-not-found
	@echo "[vm-delete] VM '$(vm)' deleted ✅"

# ---------------------------------------------------------------
# VM Status – show claim + infra status
# ---------------------------------------------------------------
vm-status:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-status vm=ok4"; exit 1)
	@echo "=== Crossplane Claim ==="
	@kubectl get openkubesvmclaim "$(vm)" -n $(namespace) 2>/dev/null || echo "No claim found"
	@echo ""
	@echo "=== Crossplane Objects ==="
	@kubectl get objects.kubernetes.crossplane.io 2>/dev/null | grep "$(vm)" || echo "No objects found"
	@echo ""
	@echo "=== VM on Infra Cluster ==="
	@kubectl get vm "$(vm)-vm" -n $(kubevirt_ns) 2>/dev/null || echo "VM not found on infra cluster"
	@echo ""
	@echo "=== Service on Infra Cluster ==="
	@kubectl get svc "$(vm)-svc" -n $(kubevirt_ns) 2>/dev/null || echo "Service not found"

# ---------------------------------------------------------------
# VM SSH – SSH into VM
# ---------------------------------------------------------------
vm-ssh:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-ssh vm=ok4"; exit 1)
	@IP=$$(kubectl get openkubesvmclaim "$(vm)" -n $(namespace) \
	  -o jsonpath='{.spec.service.loadBalancerIP}' 2>/dev/null || echo ""); \
	if [ -z "$$IP" ]; then \
	  echo "ERROR: could not read LoadBalancer IP from claim '$(vm)'"; exit 1; \
	fi; \
	echo "[vm-ssh] connecting to ubuntu@$$IP..."; \
	ssh -o StrictHostKeyChecking=no ubuntu@$$IP

# ---------------------------------------------------------------
# VM Apply – direct KubeVirt apply (no Crossplane)
# ---------------------------------------------------------------
vm-apply:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-apply vm=ok4"; exit 1)
	@test -f "kubevirt/$(vm)-vm.yaml" || \
	  (echo "ERROR: kubevirt/$(vm)-vm.yaml not found"; exit 1)
	@echo "[vm-apply] applying VM '$(vm)' directly on infra cluster..."
	kubectl apply -f "kubevirt/$(vm)-vm.yaml"
	@echo "[vm-apply] watching VM status (Ctrl+C to stop)..."
	@sleep 3
	@kubectl get vm "$(vm)-vm" -n $(kubevirt_ns) -w

# ---------------------------------------------------------------
# VM Remove – direct KubeVirt delete (no Crossplane)
# ---------------------------------------------------------------
vm-remove:
	@test -n "$(vm)" || (echo "ERROR: vm is required  →  make vm-remove vm=ok4"; exit 1)
	@test -f "kubevirt/$(vm)-vm.yaml" || \
	  (echo "ERROR: kubevirt/$(vm)-vm.yaml not found"; exit 1)
	@echo "[vm-remove] removing VM '$(vm)' from infra cluster..."
	kubectl delete -f "kubevirt/$(vm)-vm.yaml" --ignore-not-found
	@echo "[vm-remove] VM '$(vm)' removed ✅"

# ---------------------------------------------------------------
# VM List – list all OpenKubesVMs
# ---------------------------------------------------------------
vm-list:
	@echo "=== OpenKubesVM Claims ==="
	@kubectl get openkubesvmclaim -n $(namespace) 2>/dev/null || echo "No claims found"
	@echo ""
	@echo "=== VMs on Infra Cluster ==="
	@kubectl get vm -n $(kubevirt_ns) 2>/dev/null || echo "No VMs found"
