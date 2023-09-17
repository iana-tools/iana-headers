# IANA Header Generator for Internet Protocol Standards

## Table of Contents
- [Project Description](#project-description)
- [Intent](#intent)
- [Requirements](#requirements)
- [Contributing](#contributing)
- [License](#license)

---

## Project Description

The IANA Header Generator a Python script designed to automate the generation of C headers for various Internet protocol standards using data from the Internet Assigned Numbers Authority (IANA). This script can be applied to generate headers for protocols such as CoAP (Constrained Application Protocol), CBOR (Concise Binary Object Representation) (WIP) and others.

### Intent

The primary intent of this Python program is to:

1. Download the latest registry data from the IANA website for a specified Internet protocol standard.
2. Parse the downloaded data and convert it into C enumeration values suitable for inclusion in C programs.
3. Generate or update a C header file, preserving any existing values, and ensuring consistency with the IANA registry.

When triggered the script performs the following actions:

- Download the latest registry data from IANA for the specified Internet protocol standard if it is outdated or missing in the cache.
- Parse the downloaded data and generate C enumeration values.
- Update or create the C header file with the generated enumeration values, preserving any existing values.

Upon successful execution, the script will display a message indicating that the C header file has been generated or updated.

---

## Requirements

This requires at least python 3.0 and `pip install requests`.

---

## Contributing

Contributions to this project are welcome. If you find any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/mofosyne/iana-headers/issues) or submit a pull request.

<!-- Before contributing, please review the [Contributing Guidelines](CONTRIBUTING.md) for this project. -->

---

## License

This project is licensed under the GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 License. See the [LICENSE](LICENSE) file for details.
