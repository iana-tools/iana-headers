# IANA Header Generator for Internet Protocol Standards

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![C](https://img.shields.io/badge/Language-C-blue.svg)](https://en.wikipedia.org/wiki/C_(programming_language))
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff)](https://en.wikipedia.org/wiki/Python_(programming_language))
[![CI/CD Status Badge](https://github.com/mofosyne/iana-headers/actions/workflows/python-test.yml/badge.svg)](https://github.com/mofosyne/iana-headers/actions)

**STATUS: WIP, looking for people to use and provide feedback so I can lock this list down**

## Table of Contents
- [Project Description](#project-description)
- [Intent](#intent)
- [Requirements](#requirements)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)

---

## Project Description

The IANA Header Generator is a Python script designed to automate the generation of C headers for various Internet protocol standards using data from the Internet Assigned Numbers Authority (IANA). This script can be applied to generate headers for protocols such as CoAP (Constrained Application Protocol), CBOR (Concise Binary Object Representation) (WIP), and others.

For practical usage in real projects, the code generator is smart enough to recognize if you already defined an enumerated value and your value naming will take precedence.

### Intent

When triggered the script performs the following actions:

- Download the latest registry data from IANA for the specified Internet protocol standard if it is outdated or missing in the cache.
- Parse the downloaded data and generate C enumeration values.
- Update or create the C header file with the generated enumeration values, preserving any existing values.

Upon successful execution, the script will display a message indicating that the C header file has been generated or updated.

---

## Requirements

This project requires Python 3.11 or higher and uses `pip` to manage dependencies.

### Setting up the Environment

To ensure a clean and isolated environment, it's recommended to use a virtual environment (venv). Follow these steps to set up the virtual environment:

```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate
```

### Installing Dependencies

Once the virtual environment is activated, you can install the project dependencies using the provided `requirements.txt` file:

```bash
# Install dependencies using pip
pip install -r requirements.txt
```

This will install all the required packages specified in the `requirements.txt` file within the virtual environment.

---

## Usage

Alternatively, you can use the provided Makefile to manage the project. Here are some useful Makefile targets:

- `install`: Create a virtual environment and install dependencies.
- `update`: Update project dependencies.
- `generate`: Generate headers.
- `clean`: Clean generated files.

To use the Makefile, simply run `make <target>` in your terminal.

---

## Contributing

Contributions to this project are welcome. If you find any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/mofosyne/iana-headers/issues) or submit a pull request.

<!-- Before contributing, please review the [Contributing Guidelines](CONTRIBUTING.md) for this project. -->

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
