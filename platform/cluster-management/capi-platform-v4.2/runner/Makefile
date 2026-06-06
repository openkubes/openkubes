IMAGE         ?= kubernautslabs/capi-platform-runner:v4.2
KUBECONFIG_HOST ?= $(HOME)/.kube/config
ARGS          ?=
MGMT_VM_IPS   ?= 84.200.100.225 84.200.100.226 84.200.100.227

RUNNER_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT_DIR   := $(abspath $(RUNNER_DIR)/..)

DOCKER_RUN = docker run --rm -it \
	-v "$(ROOT_DIR)":/workspace \
	-v "$(KUBECONFIG_HOST)":/kubeconfig:ro \
	-e KUBECONFIG=/kubeconfig \
	-e MGMT_KUBECONFIG=/kubeconfig \
	-e RUNNER_MODE=true \
	-w /workspace \
	"$(IMAGE)"

.PHONY: help \
	build-image build-image-no-cache push-image release-image clear-image-cache \
	shell render-cluster deploy-cluster wait-cluster kubeconfig \
	install-cni install-multus deploy-full cleanup \
	check-leftovers force-clean-leftovers

help:
	@echo ""
	@echo "OpenKubes Runner Image"
	@echo ""
	@echo "Image Management:"
	@echo "  make build-image              Build runner image (with cache)"
	@echo "  make build-image-no-cache     Build runner image (no cache)"
	@echo "  make push-image               Push runner image to Docker Hub"
	@echo "  make release-image            Build (no-cache) + push  ← use this for releases"
	@echo "  make clear-image-cache        Clear cached image on all management VMs"
	@echo "  make release-image clear-image-cache  Full release cycle"
	@echo ""
	@echo "Local Runner Commands (docker run):"
	@echo "  make shell"
	@echo "  make render-cluster   ARGS='country=de provider=kubevirt cluster-name=ok1 ...'"
	@echo "  make deploy-cluster   ARGS='...'"
	@echo "  make deploy-full      ARGS='...'"
	@echo "  make cleanup          ARGS='...'"
	@echo "  make check-leftovers  ARGS='...'"
	@echo ""
	@echo "Variables:"
	@echo "  IMAGE=$(IMAGE)"
	@echo "  MGMT_VM_IPS=$(MGMT_VM_IPS)"
	@echo ""

# ---------------------------------------------------------------
# Image Management
# ---------------------------------------------------------------

build-image:
	@echo "[build] building $(IMAGE)..."
	docker build -t "$(IMAGE)" -f "$(RUNNER_DIR)/Dockerfile" "$(ROOT_DIR)"
	@echo "[build] done ✅"

build-image-no-cache:
	@echo "[build] building $(IMAGE) (no cache)..."
	docker build --no-cache -t "$(IMAGE)" -f "$(RUNNER_DIR)/Dockerfile" "$(ROOT_DIR)"
	@echo "[build] done ✅"

push-image:
	@echo "[push] pushing $(IMAGE) to Docker Hub..."
	docker push "$(IMAGE)"
	@echo "[push] done ✅"

release-image: build-image-no-cache push-image
	@echo ""
	@echo "✅ $(IMAGE) released successfully"
	@echo ""
	@docker inspect "$(IMAGE)" --format='   Digest: {{index .RepoDigests 0}}'
	@echo ""
	@echo "Next: make clear-image-cache"

clear-image-cache:
	@echo "[cache] clearing $(IMAGE) from management cluster nodes..."
	@for ip in $(MGMT_VM_IPS); do \
	  echo "  → $$ip"; \
	  ssh ubuntu@$$ip "sudo crictl rmi $(IMAGE) 2>/dev/null && echo '    deleted' || echo '    not cached'"; \
	done
	@echo "[cache] done ✅"

verify-image:
	@echo "[verify] checking scripts in $(IMAGE)..."
	docker run --rm "$(IMAGE)" ls /workspace/scripts/
	@echo ""
	@echo "[verify] checking key variables in Makefile..."
	docker run --rm "$(IMAGE)" grep -c "INFRA_CLUSTER_SECRET_NAMESPACE" /workspace/Makefile
	@echo "[verify] checking deploy-full.sh base_ns fix..."
	docker run --rm "$(IMAGE)" grep "base_ns" /workspace/scripts/deploy-full.sh

# ---------------------------------------------------------------
# Local Runner Commands
# ---------------------------------------------------------------

shell:
	$(DOCKER_RUN) bash

render-cluster:
	$(DOCKER_RUN) make render-cluster-local $(ARGS)

deploy-cluster:
	$(DOCKER_RUN) make deploy-cluster-local $(ARGS)

wait-cluster:
	$(DOCKER_RUN) make wait-cluster-local $(ARGS)

kubeconfig:
	$(DOCKER_RUN) make kubeconfig-local $(ARGS)

install-cni:
	$(DOCKER_RUN) make install-cni-local $(ARGS)

install-multus:
	$(DOCKER_RUN) make install-multus-local $(ARGS)

deploy-full:
	$(DOCKER_RUN) make deploy-full-local $(ARGS)

cleanup:
	$(DOCKER_RUN) make cleanup-local $(ARGS)

check-leftovers:
	$(DOCKER_RUN) make check-leftovers-local $(ARGS)

force-clean-leftovers:
	$(DOCKER_RUN) make force-clean-leftovers-local $(ARGS)
