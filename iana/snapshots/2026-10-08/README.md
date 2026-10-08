# IANA source snapshot — 2026-10-08

Raw registry inputs captured from IANA while running `python3 c/sync.py --dry-run` on 2026-10-08. The dry run does not edit `db/`; it refreshes the normal ignored cache. These checked-in copies preserve the inputs for parser debugging and regression tests. XML is the primary input and CSV is the configured fallback.

| Snapshot file | IANA source |
| --- | --- |
| `cbor/cbor-simple-values.xml` | https://www.iana.org/assignments/cbor-simple-values/cbor-simple-values.xml |
| `cbor/simple.csv` | https://www.iana.org/assignments/cbor-simple-values/simple.csv |
| `cbor/cbor-tags.xml` | https://www.iana.org/assignments/cbor-tags/cbor-tags.xml |
| `cbor/tags.csv` | https://www.iana.org/assignments/cbor-tags/tags.csv |
| `coap/core-parameters.xml` | https://www.iana.org/assignments/core-parameters/core-parameters.xml |
| `coap/coap-method-codes.csv` | https://www.iana.org/assignments/core-parameters/method-codes.csv |
| `coap/coap-response-codes.csv` | https://www.iana.org/assignments/core-parameters/response-codes.csv |
| `coap/coap-signaling-codes.csv` | https://www.iana.org/assignments/core-parameters/signaling-codes.csv |
| `coap/coap-options.csv` | https://www.iana.org/assignments/core-parameters/option-numbers.csv |
| `coap/coap-content-formats.csv` | https://www.iana.org/assignments/core-parameters/content-formats.csv |
| `coap/coap-signaling-options.csv` | https://www.iana.org/assignments/core-parameters/signaling-option-numbers.csv |
| `http/http-status-codes.xml` | https://www.iana.org/assignments/http-status-codes/http-status-codes.xml |
| `http/http-status-codes-1.csv` | https://www.iana.org/assignments/http-status-codes/http-status-codes-1.csv |
| `http/http-field-names.xml` | https://www.iana.org/assignments/http-fields/http-fields.xml |
| `http/field-names.csv` | https://www.iana.org/assignments/http-fields/field-names.csv |

These are immutable debugging fixtures, not the runtime cache. `c/cache/` remains ignored so ordinary syncs do not create noisy changes to the working tree. Refresh this snapshot intentionally, use a new dated directory, and update the parser tests rather than overwriting historical inputs.
