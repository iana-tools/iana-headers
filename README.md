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

The registry data is mirrored into a small database, `db/*.rec` ([GNU recutils](https://www.gnu.org/software/recutils/) text format, one file per registry). The database is the source of truth: every IANA entry carries a `Words` field (e.g. `date time string`) from which its C identifier is derived, so a published name never changes unless someone edits it.

```
IANA registries --sync--> db/*.rec --name--> db/*.rec --check--> --generate--> c/src/*.h
 (XML, CSV fallback)      (Words empty)      (Words filled)       (no network, deterministic)
```

1. **sync** fetches the registries (XML, falling back to CSV) and appends entries that are missing from `db/` with empty `Words`. It never rewrites existing `Semantics` or `Words`: when IANA's wording changes it is saved as `IANA Semantics`, and if the entry is lifecycle-tracked (provisional/temporary) it also sets `Review: pending`, so `check` blocks generation until `make review` reconciles it.
2. **name** fills `Words` for new entries using per-registry rules and records the suggestion in `Suggested Words`. Anything ambiguous (a collision, or a description too long to be a name) is left empty for a human; **review** (`make review`) walks through those interactively.
3. **check** validates the database: no unnamed entries, no duplicate names, no HTML entities (issue #9), well-formed tags.
4. **generate** turns the database into the C headers, preserving any values already defined in an existing header.
5. **verify** generates, then compiles the headers.

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

Use the provided Makefile (it creates the virtual environment on first use):

- `install`: Create a virtual environment and install dependencies.
- `update`: Update project dependencies.
- `refresh`: One full IANA update: `sync` + `name`, and a review summary of what changed; the snapshot is discarded when IANA brought nothing new (needs network, not git or GitHub).
- `sync`: Fetch IANA registries, add new entries to `db/`, and save the exact source inputs used in a dated `iana/snapshots/YYYY-MM-DD/` directory (needs network).
- `name`: Fill `Words` for new entries automatically (`python3 c/name.py --llm` can ask a local Ollama model for CBOR tag names).
- `review`: Interactively review new or unresolved names and IANA lifecycle changes; accept a suggestion, enter a name, skip with a reason, or quit and resume later. The namer's suggestion is kept beside each saved name (`python3 c/name.py --review-stats`).
- `check`: Validate `db/`.
- `test`: Run the unit tests (offline, against the checked-in IANA snapshot).
- `report`: Markdown summary of `db/` changes since `BASE=<git ref>` (default `HEAD`): new names with their C identifiers, open decisions, and renames of published names.
- `review-stats`: How often suggested names were kept, and the overrides.
- `ci`: Everything a change must pass before merging: `test`, `check`, the published-name guard against `BASE=<target branch>`, and `verify`. GitHub CI runs the same targets.
- `generate`: Generate headers from `db/` (runs `check` first, no network).
- `verify`: Generate headers, then compile them.
- `clean`: Clean generated files.

Updating after IANA publishes new entries: run `make refresh`, then `make review` for anything it lists under *Needs a decision*, then `make ci BASE=main` and commit. GitHub is optional: the **IANA Sync** workflow runs the same `make refresh` weekly and opens a pull request with the summary, and any other scheduler or CI system can call the same targets (see DEVELOPMENT.md, "IANA updates"). Review choices are saved in `db/*.rec`; the dated IANA source snapshot in `iana/snapshots/`, database changes, and regenerated headers can be reviewed and committed together. `make sync` never stages or commits files automatically. See [DEVELOPMENT.md](DEVELOPMENT.md) for the database format and snapshot details.

---

## Contributing

Contributions to this project are welcome. If you find any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/mofosyne/iana-headers/issues) or submit a pull request.

<!-- Before contributing, please review the [Contributing Guidelines](CONTRIBUTING.md) for this project. -->

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
