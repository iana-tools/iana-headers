
.PHONY: generate
generate:
	@echo "Generating Headers"
	./coap/iana-coap-c-header.py
	./cbor/iana-cbor-c-header.py

.PHONY: clean
clean:
	rm -rf ./c/*
