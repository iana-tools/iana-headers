# Default target
all: generate

# Create a virtual environment
venv: venv/touchfile
venv/touchfile: ./requirements.txt
	@echo "Installing dependencies"
	test -d venv || python3 -m venv venv
	. venv/bin/activate; venv/bin/pip install -r ./requirements.txt
	touch venv/touchfile

# Create the virtual environment and install dependencies
.PHONY: install
install: venv

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

# Generate headers from db/ (deterministic, no network). Refuses to run on a db that fails `check`.
.PHONY: generate
generate: check
	@echo "Generating Headers"
	. venv/bin/activate && cd c && python3 generate.py

# Compile the generated headers together (catches empty enums, duplicate enumerators, ...)
.PHONY: verify
verify: generate
	@echo "Compiling generated headers"
	printf '#include <stdint.h>\n#include "cbor_constants.h"\n#include "coap_constants.h"\n#include "http_constants.h"\nint main(void) { return 0; }\n' \
		| $(CC) -std=gnu11 -Wall -Wextra -fsyntax-only -I c/src -x c -

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
	@echo "  generate    : db/ → c/src/*.h (no network; runs check first)"
	@echo "  verify      : generate, then compile the headers"
	@echo "  clean       : Clean generated files"
	@echo "  help        : Display this help message"
