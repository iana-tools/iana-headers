# Default target
all: generate

# Create a virtual environment
venv: venv/touchfile
venv/touchfile: ./requirements.txt
	@echo "Installing dependencies"
	test -d venv || python3 -m venv venv
	. venv/bin/activate; venv/bin/pip install -r ./requirements.txt
	touch venv/touchfile

# Update dependencies
.PHONY: update
update: venv
	@echo "Updating dependencies"
	. venv/bin/activate && venv/bin/pip install --upgrade -r requirements.txt

# Fetch IANA registries → append empty-Words entries to db/ (needs network)
.PHONY: sync
sync: venv
	@echo "Syncing IANA registries"
	. venv/bin/activate && cd c && python3 sync.py

# Fill Words on new db entries via heuristic (or --llm for Ollama)
.PHONY: name
name: venv
	@echo "Naming new entries"
	. venv/bin/activate && cd c && python3 name.py

# Validate db/ integrity — blocks generate on errors
.PHONY: check
check: venv
	@echo "Checking db/ integrity"
	. venv/bin/activate && cd c && python3 check.py

# Generate headers from db/ (deterministic, no network)
.PHONY: generate
generate: venv
	@echo "Generating Headers"
	. venv/bin/activate && cd c && python3 generate.py

# Clean
.PHONY: clean
clean:
	@echo "Cleaning generated files"
	rm -rf ./c/cache/*
	rm -rf ./c/src/*

# Help target
.PHONY: help
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install     : Create virtual environment and install dependencies"
	@echo "  update      : Update project dependencies"
	@echo "  sync        : Fetch IANA registries → db/ (needs network)"
	@echo "  name        : Fill Words on new db entries (heuristic/LLM)"
	@echo "  check       : Validate db/ integrity"
	@echo "  generate    : db/ → c/src/*.h (no network)"
	@echo "  clean       : Clean generated files"
	@echo "  help        : Display this help message"
