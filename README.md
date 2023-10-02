# IANA Header Generator for Internet Protocol Standards

**STATUS: WIP, looking for people to use and provide feedback so I can lock this list down**

## Table of Contents
- [Project Description](#project-description)
- [Intent](#intent)
- [Requirements](#requirements)
- [Contributing](#contributing)
- [License](#license)

---

## Project Description

The IANA Header Generator a Python script designed to automate the generation of C headers for various Internet protocol standards using data from the Internet Assigned Numbers Authority (IANA). This script can be applied to generate headers for protocols such as CoAP (Constrained Application Protocol), CBOR (Concise Binary Object Representation) (WIP) and others.

For practical usage in real projects, the code generator is smart enough to recognise if you already defined an enumerated value and your value naming will take precidence.

### Intent

When triggered the script performs the following actions:

- Download the latest registry data from IANA for the specified Internet protocol standard if it is outdated or missing in the cache.
- Parse the downloaded data and generate C enumeration values.
- Update or create the C header file with the generated enumeration values, preserving any existing values.

Upon successful execution, the script will display a message indicating that the C header file has been generated or updated.

---

## Requirements

This requires at least python 3.0 and `pip install requests`.


---

## Key Insight / Challenges

* cbor semantic tags does not require submitters to give a name, so had to implement a heuristic that generates a name based on the semantic description field from the IANA cbor tag registry
    - Such as ignoring content inside brackets like `Binary UUID ([RFC4122, Section 4.1.2])` which I rendered as `CBOR_TAG_37_BINARY_UUID`
    - Ignoring sentences that reference some other standards via `define in` key phrase. e.g. `A collection of NCMS metadata elements. The key value pairs of the map are defined in AdatP-5636.4` should be rendered as `CBOR_TAG_42602_A_COLLECTION_OF_NCMS_METADATA_ELEMENTS`.
* coap signalling option number can apply to multiple coap code, so cannot generate a single enum list for that IANA registry table. Need special handling
* coap content format is based on MIME types so should take `+` and `/` into account as well as factor in the additional parameter fields. Added some special handling of certain parameters to avoid repeated words... 
    - An example of special handling is this string `application/cose; cose-type="cose-encrypt0"; Ref: [RFC9052]` where naively stripping out the non variable friendly characters to `_` would lead to repeated `COSE` mentions, when infact we want something more like `COAP_CONTENT_FORMAT_APPLICATION_COSE_ENCRYPT0`

---

## This Project Default Code Style Justification

* Why Screaming Snake Case for typedef enum and other macro constants
    - It's easier for non english people to read compared to other options like Camel Case
        - Supporting Sources. In "460: I Don’t Care What Your Math Says" one of the speaker highlighted the difficulties of readig camel case in for non english speakers [460: I Don’t Care What Your Math Says : Transcript] (https://embedded.fm/transcripts/460)

---

## Contributing

Contributions to this project are welcome. If you find any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/mofosyne/iana-headers/issues) or submit a pull request.

<!-- Before contributing, please review the [Contributing Guidelines](CONTRIBUTING.md) for this project. -->

---

## License

This project is licensed under the GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 License. See the [LICENSE](LICENSE) file for details.
