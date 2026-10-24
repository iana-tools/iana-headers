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

Everything runs through the Makefile, which creates the virtual environment on first use. `make help` lists every target with its options.

### Try it out (offline, changes nothing)

```sh
git clone https://github.com/iana-tools/iana-headers && cd iana-headers   # the c/src headers submodule is not needed
make help        # targets, grouped, with their options
make test        # unit tests against the checked-in IANA snapshot
make verify      # check db/, generate c/src/*.h, compile them
```

Open `c/src/cbor_constants.h`: the CBOR tag enum starts with a comment explaining every abbreviation used in the names (`UR`, `COSE`, `STRCT`, ...), then one identifier per tag with its IANA description.

```sh
make names-v2 OUTPUT=/tmp/names-v2.md   # proposed v2 CBOR tag names (UR_SEED, CWT, ...) beside the v1 names
make namespaces DRY_RUN=1          # the tag families in db/namespaces/cbor_tags.rec and what they match
make review-stats                  # how often suggested names were kept (empty until names are reviewed)
```

### Update from IANA (needs network; do it on a branch)

```sh
git switch -c iana-update
make refresh       # sync + name; prints a summary: what needs a decision, new names, IANA wording changes
make review        # decide what the summary lists under "Needs a decision"
make ci            # tests, check, published-name guard, compile; compares with your last commit
git add db iana/snapshots && git commit -m "IANA sync"
```

- `make refresh` saves the IANA files it used in `iana/snapshots/<date>/`, and discards them again if IANA brought nothing new. `SUMMARY=<file>` writes the summary to a file instead of the terminal.
- `make review` goes through each open entry. Pick a suggested name by number (`a` takes the first), `e` to type your own (any case or punctuation), `s` to skip it with a reason, `q` to stop; rerun to continue where you left off. Entries whose provisional/temporary IANA registration changed show the old and new IANA text: `k` keeps the name, `l` leaves it for later.
- To fix a generated name without the review, edit its `Words` in `db/*.rec` and set `Source: manual`; `make check` insists on it.
- `make report` prints the same kind of summary for your uncommitted changes, or for a whole branch with `BASE=origin/main`: new names with their C identifiers, open decisions, and any rename of an already-published name (which `make ci` rejects unless the record has `Previous Words: <old words>`).
- `make ci` is what must pass before merging: tests, `check`, that published-name guard, and compiling the headers. It compares with your last commit; for a branch with several commits use `BASE=origin/main`, and without git `BASE_DIR=<copy of the published db/>`.

GitHub is optional: the **IANA Sync** workflow runs the same `make refresh` weekly and opens a pull request with the summary, and CI runs `make ci`'s steps on every pull request. Any other scheduler or CI system can call the same targets (see [DEVELOPMENT.md](DEVELOPMENT.md), "IANA updates").

### Targets

| Target | What it does |
| --- | --- |
| `install`, `update` | Create the virtual environment / upgrade its dependencies |
| `refresh` | One full IANA update: `sync` + `name` + review summary (`SUMMARY=<file>`) |
| `sync` | Fetch the IANA registries, append new entries to `db/` with empty names, save a dated snapshot |
| `name` | Name new entries with the per-registry rules (`python3 c/name.py --llm` asks a local Ollama model for CBOR tag names) |
| `review` | Interactively decide unnamed entries and IANA lifecycle changes |
| `review-stats` | How often suggested names were kept, and every override |
| `namespaces` | Assign tag families from `db/namespaces/` to records after editing a table (`DRY_RUN=1`) |
| `names-v2` | Preview the proposed v2 CBOR tag names (`OUTPUT=<file>`); changes nothing |
| `check` | Validate `db/` |
| `test` | Unit tests (offline) |
| `report` | Markdown summary of `db/` changes since `BASE=<git ref>` or `BASE_DIR=<dir>` (`STRICT=1`, `REPORT=<file>`) |
| `ci` | Everything to pass before merging (`BASE=<target branch>` or `BASE_DIR=<dir>`) |
| `generate`, `verify` | Generate `c/src/*.h` from `db/`; `verify` also compiles them |
| `clean` | Remove the download cache and generated headers |

The scripts behind the targets take more options; run them from `c/` with `--help` (e.g. `python3 sync.py --help` for `--dry-run`, `--verbose`). See [DEVELOPMENT.md](DEVELOPMENT.md) for the database format, namespaces, the v2 naming proposal, and snapshots.

---

## Contributing

Contributions to this project are welcome. If you find any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/mofosyne/iana-headers/issues) or submit a pull request.

<!-- Before contributing, please review the [Contributing Guidelines](CONTRIBUTING.md) for this project. -->

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
