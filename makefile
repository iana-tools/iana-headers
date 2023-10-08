
.PHONY: generate
generate:
	@echo "Generating Headers"
	cd c; ./iana-coap-c-header.py
	cd c; ./iana-cbor-c-header.py
	cd c; ./iana-http-c-header.py

.PHONY: clean
clean:
	rm -rf ./c/cache/*
	rm -rf ./c/src/*
