SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

country ?=
provider ?=
cluster-name ?=
# namespace defaults to cluster-name so each cluster gets its own namespace.
# Override explicitly if needed: namespace=my-custom-ns
namespace ?= $(cluster-name)
endpoint-ip ?=

kubernetes-version ?= v1.34.1
control-plane-replicas ?= 1
worker-replicas ?= 2

cni ?= calico
multus ?= false

outdir ?= rendered

IMAGE ?= openkubes/capi-platform-runner:v4.2
KUBECONFIG ?= $(HOME)/.kube/config
MGMT_KUBECONFIG ?= $(KUBECONFIG)
RUNNER_MODE ?= false

COUNTRY_ENV := config/countries/$(country).env
PROVIDER_ENV := config/providers/$(provider).env
RENDERED_FILE := $(outdir)/$(cluster-name).yaml
KUBECONFIG_FILE := $(outdir)/$(cluster-name).kubeconfig

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

DOCKER_RUN = docker run --rm \
	-v "$(ROOT_DIR)":/workspace \
	-v "$(KUBECONFIG)":/kubeconfig:ro \
	-e KUBECONFIG=/kubeconfig \
	-e MGMT_KUBECONFIG=/kubeconfig \
	-e RUNNER_MODE=true \
	-w /workspace \
	"$(IMAGE)"

.PHONY: help validate-vars check-deps
.PHONY: render-cluster deploy-cluster wait-cluster kubeconfig install-cni install-multus deploy-full cleanup
.PHONY: render-cluster-local deploy-cluster-local wait-cluster-local kubeconfig-local
.PHONY: install-cni-local install-multus-local deploy-full-local cleanup-local
.PHONY: delete-cluster check-leftovers force-clean-leftovers show-rendered
.PHONY: check-leftovers-local force-clean-leftovers-local

help:
	@echo "Targets:"
	@echo "  make render-cluster country=de provider=kubevirt cluster-name=ok1 endpoint-ip=10.10.10.50"
	@echo "  make deploy-cluster country=de provider=kubevirt cluster-name=ok1 endpoint-ip=10.10.10.50"
	@echo "  make wait-cluster country=de provider=kubevirt cluster-name=ok1"
	@echo "  make kubeconfig country=de provider=kubevirt cluster-name=ok1"
	@echo "  make install-cni country=de provider=kubevirt cluster-name=ok1 cni=calico"
	@echo "  make install-multus country=de provider=kubevirt cluster-name=ok1"
	@echo "  make deploy-full country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50"
	@echo "  make cleanup country=de provider=kubevirt cluster-name=ok1"
	@echo "  make check-leftovers cluster-name=ok1"
	@echo "  make force-clean-leftovers cluster-name=ok1"
	@echo ""
	@echo "  namespace defaults to cluster-name (each cluster gets its own namespace)."
	@echo "  Override with: namespace=my-custom-ns"

validate-vars:
	@test -n "$(country)" || (echo "ERROR: country is required"; exit 1)
	@test -n "$(provider)" || (echo "ERROR: provider is required"; exit 1)
	@test -n "$(cluster-name)" || (echo "ERROR: cluster-name is required"; exit 1)
	@test -f "$(COUNTRY_ENV)" || (echo "ERROR: missing $(COUNTRY_ENV)"; exit 1)
	@test -f "$(PROVIDER_ENV)" || (echo "ERROR: missing $(PROVIDER_ENV)"; exit 1)
	@test "$(cni)" = "calico" -o "$(cni)" = "cilium" || (echo "ERROR: cni must be calico or cilium"; exit 1)
	@test "$(multus)" = "true" -o "$(multus)" = "false" || (echo "ERROR: multus must be true or false"; exit 1)

check-deps:
ifeq ($(RUNNER_MODE),true)
	@./scripts/check-deps.sh
else
	@command -v docker >/dev/null 2>&1 || (echo "ERROR: docker missing"; exit 1)
	@echo "Host dependencies found."
endif

render-cluster:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) render-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
else
	$(DOCKER_RUN) make render-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
endif

deploy-cluster:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) deploy-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
else
	$(DOCKER_RUN) make deploy-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
endif

wait-cluster:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) wait-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace)
else
	$(DOCKER_RUN) make wait-cluster-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace)
endif

kubeconfig:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) kubeconfig-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
else
	$(DOCKER_RUN) make kubeconfig-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
endif

install-cni:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) install-cni-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) cni=$(cni) outdir=$(outdir)
else
	$(DOCKER_RUN) make install-cni-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) cni=$(cni) outdir=$(outdir)
endif

install-multus:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) install-multus-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
else
	$(DOCKER_RUN) make install-multus-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
endif

deploy-full:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) deploy-full-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
else
	$(DOCKER_RUN) make deploy-full-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) kubernetes-version=$(kubernetes-version) control-plane-replicas=$(control-plane-replicas) worker-replicas=$(worker-replicas) cni=$(cni) multus=$(multus) outdir=$(outdir) endpoint-ip=$(endpoint-ip)
endif

cleanup:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) cleanup-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
else
	$(DOCKER_RUN) make cleanup-local country=$(country) provider=$(provider) cluster-name=$(cluster-name) namespace=$(namespace) outdir=$(outdir)
endif

check-leftovers:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) check-leftovers-local namespace=$(namespace) cluster-name=$(cluster-name)
else
	$(DOCKER_RUN) make check-leftovers-local namespace=$(namespace) cluster-name=$(cluster-name)
endif

force-clean-leftovers:
ifeq ($(RUNNER_MODE),true)
	$(MAKE) force-clean-leftovers-local namespace=$(namespace) cluster-name=$(cluster-name)
else
	$(DOCKER_RUN) make force-clean-leftovers-local namespace=$(namespace) cluster-name=$(cluster-name)
endif

render-cluster-local: validate-vars check-deps
	@mkdir -p "$(outdir)"
	@set -a; \
	source "$(COUNTRY_ENV)"; \
	source "$(PROVIDER_ENV)"; \
	$(if $(endpoint-ip),export CONTROL_PLANE_ENDPOINT_IP="$(endpoint-ip)";,) \
	export KUBEVIRT_VM_NAMESPACE="$(namespace)"; \
	export INFRA_CLUSTER_SECRET_BASE_NAME="$${INFRA_CLUSTER_SECRET_BASE_NAME:-external-infra-kubeconfig}"; \
	export INFRA_CLUSTER_SECRET_NAME="$${INFRA_CLUSTER_SECRET_BASE_NAME}-$(cluster-name)"; \
	export INFRA_CLUSTER_SECRET_NAMESPACE="$(namespace)"; \
	export CLUSTER_NAME="$(cluster-name)"; \
	export NAMESPACE="$(namespace)"; \
	export KUBERNETES_VERSION="$(kubernetes-version)"; \
	export CONTROL_PLANE_REPLICAS="$(control-plane-replicas)"; \
	export WORKER_REPLICAS="$(worker-replicas)"; \
	./scripts/render.sh "$(RENDERED_FILE)"
	@echo "Rendered: $(RENDERED_FILE)"

deploy-cluster-local: render-cluster-local
	@echo "Deploying cluster $(cluster-name) with provider $(provider)"
	@kubectl apply -f "$(RENDERED_FILE)"

wait-cluster-local: validate-vars
	@./scripts/wait-cluster.sh "$(cluster-name)" "$(namespace)"

kubeconfig-local: validate-vars
	@mkdir -p "$(outdir)"
	@clusterctl get kubeconfig "$(cluster-name)" -n "$(namespace)" > "$(KUBECONFIG_FILE)"
	@echo "Wrote kubeconfig: $(KUBECONFIG_FILE)"

install-cni-local: validate-vars kubeconfig-local
	@test -f "$(KUBECONFIG_FILE)" || (echo "ERROR: missing $(KUBECONFIG_FILE)"; exit 1)
	@if [ "$(cni)" = "calico" ]; then \
	  echo "Installing Calico into workload cluster $(cluster-name)"; \
	  kubectl --kubeconfig "$(KUBECONFIG_FILE)" apply -f addons/calico/calico.yaml; \
	elif [ "$(cni)" = "cilium" ]; then \
	  echo "Installing Cilium into workload cluster $(cluster-name)"; \
	  kubectl --kubeconfig "$(KUBECONFIG_FILE)" apply -f addons/cilium/cilium.yaml; \
	else \
	  echo "ERROR: unsupported cni $(cni)"; exit 1; \
	fi

install-multus-local: validate-vars kubeconfig-local
	@test -f "$(KUBECONFIG_FILE)" || (echo "ERROR: missing $(KUBECONFIG_FILE)"; exit 1)
	@echo "Installing Multus into workload cluster $(cluster-name)"
	@kubectl --kubeconfig "$(KUBECONFIG_FILE)" apply -f addons/multus/multus.yaml

deploy-full-local: validate-vars check-deps
	@set -a; \
	source "$(COUNTRY_ENV)"; \
	source "$(PROVIDER_ENV)"; \
	$(if $(endpoint-ip),export CONTROL_PLANE_ENDPOINT_IP="$(endpoint-ip)";,) \
	export KUBEVIRT_VM_NAMESPACE="$(namespace)"; \
	export INFRA_CLUSTER_SECRET_BASE_NAME="$${INFRA_CLUSTER_SECRET_BASE_NAME:-external-infra-kubeconfig}"; \
	export INFRA_CLUSTER_SECRET_NAME="$${INFRA_CLUSTER_SECRET_BASE_NAME}-$(cluster-name)"; \
	export INFRA_CLUSTER_SECRET_NAMESPACE="$(namespace)"; \
	export MGMT_KUBECONFIG="$${MGMT_KUBECONFIG:-$${KUBECONFIG:-}}"; \
	export WORKLOAD_KUBECONFIG="$${WORKLOAD_KUBECONFIG:-$(KUBECONFIG_FILE)}"; \
	export CLUSTER_NAME="$(cluster-name)"; \
	export NAMESPACE="$(namespace)"; \
	export KUBERNETES_VERSION="$(kubernetes-version)"; \
	export CONTROL_PLANE_REPLICAS="$(control-plane-replicas)"; \
	export WORKER_REPLICAS="$(worker-replicas)"; \
	export CNI_PLUGIN="$(cni)"; \
	export MULTUS_ENABLED="$(multus)"; \
	./scripts/deploy-full.sh

cleanup-local: validate-vars check-deps
	@set -a; \
	source "$(COUNTRY_ENV)"; \
	source "$(PROVIDER_ENV)"; \
	export MGMT_KUBECONFIG="$${MGMT_KUBECONFIG:-$${KUBECONFIG:-}}"; \
	export WORKLOAD_KUBECONFIG="$${WORKLOAD_KUBECONFIG:-$(KUBECONFIG_FILE)}"; \
	export CLUSTER_NAME="$(cluster-name)"; \
	export NAMESPACE="$(namespace)"; \
	export COUNTRY="$(country)"; \
	export PROVIDER="$(provider)"; \
	export INFRA_CLUSTER_SECRET_BASE_NAME="$${INFRA_CLUSTER_SECRET_BASE_NAME:-external-infra-kubeconfig}"; \
	./scripts/cleanup.sh

delete-cluster: validate-vars
	@echo "Deleting cluster $(cluster-name)"
	@kubectl delete cluster "$(cluster-name)" -n "$(namespace)" --ignore-not-found=true

check-leftovers-local:
	@./scripts/check-leftovers.sh "$(namespace)" "$(cluster-name)"

force-clean-leftovers-local:
	@./scripts/force-clean-leftovers.sh "$(namespace)" "$(cluster-name)"

show-rendered: validate-vars
	@cat "$(RENDERED_FILE)"