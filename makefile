
.PHONY: generate
generate:
	@echo "Generating Headers"
	./coap/iana-coap-header.py

.PHONY: clean
clean:
	rm -rf ./c/*
