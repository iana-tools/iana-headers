# Define the path to the virtual environment
VENV := venv

# Default target
all: generate

# Activate the virtual environment
activate_venv:
	@echo "Activating virtual environment"
	. $(VENV)/bin/activate

# Create a virtual environment
.PHONY: venv
venv:
	python3 -m venv $(VENV)

# Install dependencies
.PHONY: install
install: venv
	@echo "Installing dependencies"
	$(VENV)/bin/pip install -r requirements.txt

# Update dependencies
.PHONY: update
update: venv
	@echo "Updating dependencies"
	$(VENV)/bin/pip install --upgrade -r requirements.txt

# Generate headers
.PHONY: generate
generate: activate_venv
	@echo "Generating Headers"
	cd c && ./c_header_cbor.py
	cd c && ./c_header_coap.py
	cd c && ./c_header_http.py

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
	@echo "  generate    : Generate headers"
	@echo "  clean       : Clean generated files"
	@echo "  help        : Display this help message"
