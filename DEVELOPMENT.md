# Development Notes

## Key Insights and Challenges

### CBOR Semantic Tags Naming Heuristic
- The CBOR semantic tags don't always have a clear name provided by submitters.
- Implemented a heuristic to generate names based on the semantic description field from the IANA CBOR tag registry.
    - Ignored content inside brackets like `Binary UUID ([RFC4122, Section 4.1.2])`, rendered as `CBOR_TAG_37_BINARY_UUID`.
    - Ignored sentences that reference other standards via `define in` key phrases, such as `A collection of NCMS metadata elements. The key value pairs of the map are defined in AdatP-5636.4`, rendered as `CBOR_TAG_42602_A_COLLECTION_OF_NCMS_METADATA_ELEMENTS`.

### Handling CoAP Signalling Option Numbers
- CoAP signalling option numbers can apply to multiple CoAP codes, requiring special handling.
- Unable to generate a single enum list for the IANA registry table due to this complexity.

### CoAP Content Format Handling
- CoAP content format is based on MIME types and requires handling of special characters like `+` and `/`.
- Additional parameter fields need to be factored in.
- Special handling of certain parameters to avoid repeated words.
    - For example, `application/cose; cose-type="cose-encrypt0"; Ref: [RFC9052]` should be rendered as `COAP_CONTENT_FORMAT_APPLICATION_COSE_ENCRYPT0`.

## Code Style Justification

### Use of Screaming Snake Case
- Typedef enums and other macro constants use screaming snake case for readability.
- Easier for non-English speakers to read compared to camel case.
    - Supporting sources: In "460: I Don’t Care What Your Math Says," one of the speakers highlighted the difficulties of reading camel case for non-English speakers ([Transcript](https://embedded.fm/transcripts/460)).

## Project Structure Justification

### Arrangement by Language Family
- Project folder structure is organized in terms of language family rather than protocol.
- Better reflects the likelihood of a project using one language and toolset while potentially utilizing multiple protocols.

