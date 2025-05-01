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

# Generate headers
.PHONY: generate
generate: venv
	@echo "Generating Headers"
	. venv/bin/activate && \
	cd c && \
	./c_header_cbor.py && \
	./c_header_coap.py && \
	./c_header_http.py

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
