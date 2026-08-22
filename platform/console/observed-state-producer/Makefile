.PHONY: verify test compile manifest-check

verify: test compile manifest-check

test:
	python3 -m unittest discover -s . -p 'test_*.py'

compile:
	python3 -m py_compile app.py test_app.py test_mtls.py

manifest-check:
	ruby manifest_test.rb
