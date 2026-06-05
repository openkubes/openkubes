FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HELM_VERSION=v3.18.0
ENV KUBECTL_VERSION=v1.34.1
ENV CLUSTERCTL_VERSION=v1.12.5
ENV KUSTOMIZE_VERSION=v5.7.1
ENV YQ_VERSION=v4.44.6

RUN apt-get update && apt-get install -y \
    bash \
    ca-certificates \
    curl \
    git \
    gettext-base \
    gzip \
    jq \
    make \
    openssh-client \
    tar \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/kubectl \
    https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl \
    && chmod +x /usr/local/bin/kubectl

RUN curl -fsSL -o /usr/local/bin/clusterctl \
    https://github.com/kubernetes-sigs/cluster-api/releases/download/${CLUSTERCTL_VERSION}/clusterctl-linux-amd64 \
    && chmod +x /usr/local/bin/clusterctl

RUN curl -fsSL https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz -o /tmp/helm.tar.gz \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && rm -rf /tmp/helm.tar.gz /tmp/linux-amd64

RUN curl -fsSL \
    https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz \
    -o /tmp/kustomize.tar.gz \
    && tar -xzf /tmp/kustomize.tar.gz -C /tmp \
    && mv /tmp/kustomize /usr/local/bin/kustomize \
    && chmod +x /usr/local/bin/kustomize \
    && rm -f /tmp/kustomize.tar.gz

RUN curl -fsSL -o /usr/local/bin/yq \
    https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64 \
    && chmod +x /usr/local/bin/yq

WORKDIR /workspace

# Copy the platform code into the image so the runner works standalone
# (no volume mount needed – used when running as a Kubernetes Job)
COPY Makefile ./
COPY scripts/ ./scripts/
COPY templates/ ./templates/
COPY config/ ./config/
COPY addons/ ./addons/

COPY runner/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chmod +x scripts/*.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
