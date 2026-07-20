# OpenKubes — platform repository Makefile
# The knowledge graph is a derived projection of Git: destroy and rebuild anytime.

DOCS      := docs
GRAPH_PY  := $(DOCS)/okgraph.py
JSON      := $(DOCS)/knowledge-graph.json
TEMPLATE  := $(DOCS)/knowledge-graph-template.html
STANDALONE:= $(DOCS)/openkubes_knowledge_graph_force_layout.html

.PHONY: help graph graph-json graph-html graph-serve graph-stats

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

graph: graph-json graph-html ## Rebuild the knowledge graph (JSON + standalone HTML)
	@echo ""
	@echo "✅ Knowledge graph rebuilt."
	@echo "   Preview : make graph-serve"
	@echo "   Publish : commit $(JSON) + $(STANDALONE), upload standalone HTML to kubernauts.de"

VENV   := .venv
PYTHON := $(VENV)/bin/python3

$(VENV): ## Create local venv with graph dependencies
	@python3 -m venv $(VENV)
	@$(PYTHON) -m pip install -q networkx
	@echo "  ✔ venv ready ($(VENV))"

graph-json: $(VENV) ## Extract graph from Git (ADRs, commits, issues) → knowledge-graph.json
	@cd $(DOCS) && ../$(PYTHON) okgraph.py build ..

graph-html: ## Embed JSON into the D3 template → standalone viewer HTML
	@python3 -c "\
	tpl = open('$(TEMPLATE)').read(); \
	data = open('$(JSON)').read(); \
	assert '/*__GRAPH_DATA__*/' in tpl, 'placeholder missing in template'; \
	open('$(STANDALONE)','w').write(tpl.replace('/*__GRAPH_DATA__*/', data)); \
	print('  ✔ $(STANDALONE)')"

graph-serve: ## Preview the standalone viewer locally (http://localhost:8000)
	@echo "→ http://localhost:8000/openkubes_knowledge_graph_force_layout.html  (Ctrl-C to stop)"
	@cd $(DOCS) && python3 -m http.server 8000

graph-stats: ## Print graph summary (requires prior graph-json)
	@cd $(DOCS) && python3 okgraph.py stats
