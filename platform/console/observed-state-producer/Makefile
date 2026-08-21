.PHONY: verify test compile manifest-check

verify: test compile manifest-check

test:
	python3 -m unittest discover -s . -p 'test_*.py'

compile:
	python3 -m py_compile app.py test_app.py

manifest-check:
	ruby -e 'require "yaml"; docs=YAML.load_stream(File.read("manifests.yaml")); abort("expected 7 resources") unless docs.length == 7; abort("invalid resource") unless docs.all? { |doc| doc.is_a?(Hash) && doc["apiVersion"] && doc["kind"] && doc.dig("metadata", "name") }'
