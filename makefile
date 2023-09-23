
.PHONY: generate
generate:
	@echo "Generating Headers"
	cd coap; ./iana-coap-c-header.py
	cd cbor; ./iana-cbor-c-header.py
	cd http; ./iana-http-c-header.py

.PHONY: clean
clean:
	rm -rf ./coap/cache/*
	rm -rf ./coap/c/*
	rm -rf ./cbor/cache/*
	rm -rf ./cbor/c/*
	rm -rf ./http/cache/*
	rm -rf ./http/c/*
