IMAGE ?= openkubes/capi-platform-runner:v4.2
KUBECONFIG_HOST ?= $(HOME)/.kube/config
ARGS ?=

RUNNER_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT_DIR := $(abspath $(RUNNER_DIR)/..)

DOCKER_RUN = docker run --rm -it \
	-v "$(ROOT_DIR)":/workspace \
	-v "$(KUBECONFIG_HOST)":/kubeconfig:ro \
	-e KUBECONFIG=/kubeconfig \
	-e MGMT_KUBECONFIG=/kubeconfig \
	-e RUNNER_MODE=true \
	-w /workspace \
	"$(IMAGE)"

.PHONY: help build-image shell render-cluster deploy-cluster wait-cluster kubeconfig install-cni install-multus deploy-full cleanup check-leftovers force-clean-leftovers

help:
	@echo "Targets:"
	@echo "  make build-image"
	@echo "  make shell"
	@echo "  make render-cluster"
	@echo "  make deploy-cluster"
	@echo "  make wait-cluster"
	@echo "  make kubeconfig"
	@echo "  make install-cni"
	@echo "  make install-multus"
	@echo "  make deploy-full"
	@echo "  make cleanup"
	@echo "  make check-leftovers"
	@echo "  make force-clean-leftovers"

build-image:
	docker build -t "$(IMAGE)" -f "$(RUNNER_DIR)/Dockerfile" "$(ROOT_DIR)"

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