require "yaml"

resources = YAML.load_stream(File.read(File.join(__dir__, "manifests.yaml")))
abort("expected seven resources") unless resources.length == 7
abort("invalid resource") unless resources.all? { |resource| resource.is_a?(Hash) && resource["apiVersion"] && resource["kind"] && resource.dig("metadata", "name") }
abort("Secret values must not be committed") if resources.any? { |resource| resource["kind"] == "Secret" }

deployment = resources.find { |resource| resource["kind"] == "Deployment" }
container = deployment.dig("spec", "template", "spec", "containers", 0)
environment = container.fetch("env").to_h { |item| [item.fetch("name"), item.fetch("value")] }

abort("producer must expose only 8443/https") unless container.fetch("ports") == [{ "name" => "https", "containerPort" => 8443 }]
abort("producer must listen on 8443") unless environment["OK_OBSERVER_PORT"] == "8443"
abort("exact SPIFFE client identity is required") unless environment["OK_OBSERVER_TLS_CLIENT_IDENTITY"] == "spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff"
%w[OK_OBSERVER_TLS_CERT_FILE OK_OBSERVER_TLS_KEY_FILE OK_OBSERVER_TLS_CLIENT_CA_FILE].each do |name|
  abort("#{name} must use the read-only producer mount") unless environment.fetch(name).start_with?("/var/run/secrets/openkubes/producer/")
end
%w[readinessProbe livenessProbe].each do |probe|
  abort("#{probe} must use HTTPS") unless container.dig(probe, "httpGet", "scheme") == "HTTPS"
end

volume = deployment.dig("spec", "template", "spec", "volumes").find { |item| item["name"] == "producer-tls" }
abort("producer TLS Secret contract is missing") unless volume&.dig("secret", "secretName") == "observed-state-producer-tls"
abort("producer TLS Secret must be read-only") unless container.fetch("volumeMounts").find { |item| item["name"] == "producer-tls" }&.fetch("readOnly")

network_policy = resources.find { |resource| resource["kind"] == "NetworkPolicy" }
abort("NetworkPolicy must expose only the TLS port") unless network_policy.dig("spec", "ingress", 0, "ports") == [{ "protocol" => "TCP", "port" => 8443 }]
