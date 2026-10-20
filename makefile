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

# Fetch IANA registries → append empty-Words entries to db/ and save used source files near db/ (needs network)
.PHONY: sync
sync: venv
	@echo "Syncing IANA registries and saving a dated source snapshot"
	. venv/bin/activate && cd c && python3 sync.py --snapshot

# Fill Words on new db entries via heuristic (or --llm for Ollama)
.PHONY: name
name: venv
	@echo "Naming new entries"
	. venv/bin/activate && cd c && python3 name.py

# Review new or unresolved names interactively; choices are written to db/
.PHONY: review
review: venv
	@echo "Reviewing new IANA names"
	. venv/bin/activate && cd c && python3 name.py --interactive

# Validate db/ integrity — blocks generate on errors
.PHONY: check
check: venv
	@echo "Checking db/ integrity"
	. venv/bin/activate && cd c && python3 check.py

# Unit tests for the parsers, namer, review and report (offline, uses the checked-in IANA snapshot)
.PHONY: test
test: venv
	@echo "Running unit tests"
	. venv/bin/activate && cd c && python3 -m unittest discover -p 'test_*.py'

# One IANA update anywhere (cron, any CI, by hand): sync + name, discard the snapshot if nothing changed,
# and print a review summary (or write it to SUMMARY=<file>). The GitHub sync workflow wraps this.
.PHONY: refresh
refresh: venv
	. venv/bin/activate && cd c && python3 refresh.py $(if $(SUMMARY),--summary "$(abspath $(SUMMARY))") \
		$(if $(INTRO),--intro "$(INTRO)")

# Markdown summary of db/ changes since BASE (a git ref, default HEAD) or BASE_DIR (a copy of db/, no git
# needed): new names, decisions left, breaking renames. STRICT=1 fails on an undocumented rename/removal of a
# published name; REPORT=<file> writes the Markdown there.
BASE ?= HEAD
.PHONY: report
report: venv
	. venv/bin/activate && cd c && python3 report.py \
		$(if $(BASE_DIR),--base-dir "$(abspath $(BASE_DIR))",--base $(BASE)) $(if $(STRICT),--strict) \
		$(if $(REPORT),--output "$(abspath $(REPORT))")

# Everything a change must pass before it is merged; GitHub CI runs the same targets.
# Pass the branch it will be merged into (make ci BASE=main), or without git a copy of the published
# db/ (make ci BASE_DIR=../db-published)
.PHONY: ci
ci: test check
	$(MAKE) report STRICT=1 REPORT=$(or $(REPORT),/dev/null)
	$(MAKE) verify

# How often reviewers accepted the suggested names, and what they changed
.PHONY: review-stats
review-stats: venv
	. venv/bin/activate && cd c && python3 name.py --review-stats

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
	@echo "  refresh     : sync + name + review summary; no snapshot kept if IANA brought nothing new (needs network)"
	@echo "  sync        : Fetch IANA registries → db/ and save a dated snapshot under iana/ (needs network)"
	@echo "  name        : Fill Words on new db entries automatically (heuristic/LLM)"
	@echo "  review      : Interactively accept, edit, or skip new/unresolved names"
	@echo "  check       : Validate db/ integrity"
	@echo "  test        : Run the unit tests (offline)"
	@echo "  report      : Summarise db/ changes since BASE=<git ref> (default HEAD) as Markdown"
	@echo "  review-stats: How often suggested names were accepted"
	@echo "  ci          : test + check + published-name guard + verify; run before merging (BASE=<target branch>)"
	@echo "  generate    : db/ → c/src/*.h (no network; runs check first)"
	@echo "  verify      : generate, then compile the headers"
	@echo "  clean       : Clean generated files"
	@echo "  help        : Display this help message"
