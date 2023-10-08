
.PHONY: generate
generate:
	@echo "Generating Headers"
	cd c; ./c_header_cbor.py
	cd c; ./c_header_coap.py
	cd c; ./c_header_http.py

.PHONY: clean
clean:
	rm -rf ./c/cache/*
	rm -rf ./c/src/*
