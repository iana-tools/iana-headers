# `make help` lists the targets below from their `## description` comments and the `##@ Section` lines,
# so a new target only needs a `##` comment to be documented.

# Default target
all: generate

# Create a virtual environment; rebuilt only when requirements.txt changes
venv: venv/touchfile
venv/touchfile: ./requirements.txt
	@echo "Installing dependencies"
	test -d venv || python3 -m venv venv
	. venv/bin/activate; venv/bin/pip install -r ./requirements.txt
	touch venv/touchfile

##@ Setup

.PHONY: install
install: venv ## Create the virtual environment and install dependencies

.PHONY: update
update: venv ## Upgrade the dependencies in the virtual environment
	@echo "Updating dependencies"
	. venv/bin/activate && venv/bin/pip install --upgrade -r requirements.txt

##@ IANA updates (sync needs network)

# The GitHub sync workflow wraps `refresh`; cron or another CI system can call it the same way.
.PHONY: refresh
refresh: venv ## sync + name + review summary; drops the snapshot if nothing changed [SUMMARY=<file>] [INTRO=<text>]
	. venv/bin/activate && cd c && python3 refresh.py $(if $(SUMMARY),--summary "$(abspath $(SUMMARY))") \
		$(if $(INTRO),--intro "$(INTRO)")

.PHONY: sync
sync: venv ## Fetch IANA registries into db/ (new entries get empty Words) and save a dated snapshot
	@echo "Syncing IANA registries and saving a dated source snapshot"
	. venv/bin/activate && cd c && python3 sync.py --snapshot

.PHONY: name
name: venv ## Fill Words for new entries with the per-registry heuristics
	@echo "Naming new entries"
	. venv/bin/activate && cd c && python3 name.py

.PHONY: review
review: venv ## Interactively decide new/unnamed entries and IANA lifecycle changes; resumable
	@echo "Reviewing new IANA names"
	. venv/bin/activate && cd c && python3 name.py --interactive

.PHONY: names-v2
names-v2: venv ## Preview proposed v2 CBOR tag names from the IANA fields; changes nothing [OUTPUT=<file>]
	. venv/bin/activate && cd c && python3 cbor_names_v2.py $(if $(OUTPUT),--output "$(abspath $(OUTPUT))")

.PHONY: review-stats
review-stats: venv ## How often suggested names were kept, and every override
	. venv/bin/activate && cd c && python3 name.py --review-stats

##@ Checks (offline)

.PHONY: check
check: venv ## Validate db/ (blocks generate on errors)
	@echo "Checking db/ integrity"
	. venv/bin/activate && cd c && python3 check.py

.PHONY: test
test: venv ## Run the unit tests (uses the checked-in IANA snapshot)
	@echo "Running unit tests"
	. venv/bin/activate && cd c && python3 -m unittest discover -p 'test_*.py'

# BASE is a git ref; BASE_DIR a copy of db/ (no git needed). STRICT=1 fails on an undocumented
# rename/removal of a published name.
BASE ?= HEAD
.PHONY: report
report: venv ## Markdown summary of db/ changes [BASE=<git ref>|BASE_DIR=<dir>] [STRICT=1] [REPORT=<file>]
	. venv/bin/activate && cd c && python3 report.py \
		$(if $(BASE_DIR),--base-dir "$(abspath $(BASE_DIR))",--base $(BASE)) $(if $(STRICT),--strict) \
		$(if $(REPORT),--output "$(abspath $(REPORT))")

# GitHub CI runs the same targets.
.PHONY: ci
ci: test check ## Everything to pass before merging: test, check, name guard, verify [BASE=<target branch>|BASE_DIR=<dir>]
	$(MAKE) report STRICT=1 REPORT=$(or $(REPORT),/dev/null)
	$(MAKE) verify

##@ Headers

.PHONY: generate
generate: check ## Generate c/src/*.h from db/ (default target; deterministic, no network)
	@echo "Generating Headers"
	. venv/bin/activate && cd c && python3 generate.py

# Catches empty enums, duplicate enumerators, ...
.PHONY: verify
verify: generate ## Generate, then compile the headers together
	@echo "Compiling generated headers"
	printf '#include <stdint.h>\n#include "cbor_constants.h"\n#include "coap_constants.h"\n#include "http_constants.h"\nint main(void) { return 0; }\n' \
		| $(CC) -std=gnu11 -Wall -Wextra -fsyntax-only -I c/src -x c -

.PHONY: clean
clean: ## Remove the download cache and generated headers
	@echo "Cleaning generated files"
	rm -rf ./c/cache/*
	rm -rf ./c/src/*

##@ Help

.PHONY: help
help: ## Show this list
	@echo "Usage: make [target] [VAR=value ...]"
	@awk 'BEGIN { FS = ":.*## " } \
		/^##@/ { printf "\n%s\n", substr($$0, 5) } \
		/^[a-zA-Z0-9_-]+:.*## / { printf "  %-13s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""
	@echo "The tools take more options than these variables expose: python3 c/<tool>.py --help"
	@echo "(sync, name, refresh, report, generate)."
