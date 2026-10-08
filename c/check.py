#!/usr/bin/env python3
"""
check.py — validate db/*.rec integrity before generate.

Exits non-zero on any failure, printing ALL errors (not just first).
"""

import os
import re
import sys

import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(os.path.dirname(script_dir), 'db')

# 'skip' = deliberately excluded from the generated headers (kept so `make sync` does not re-add it)
VALID_SOURCES = {'heuristic', 'llm', 'manual', 'needs-manual', 'new', 'skip'}
REQUIRED_FIELDS = ('Tag', 'Words', 'Semantics', 'Reference', 'Source')
HTML_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#\d+;')
TOKEN_RE = re.compile(r'^[a-z0-9_]+$')


def check_file(db_file):
    errors = []
    fname = os.path.basename(db_file)
    records = recfile.read(db_file)

    seen_tags = {}    # parsed tag key -> first record index
    seen_words = {}   # (enum scope, words) -> first tag

    for i, rec in enumerate(records):
        tag = rec.get('Tag', '').strip()
        loc = f"{fname} Tag={tag!r}"

        # 1. Required fields present (Reference may legitimately be empty, Semantics may not)
        for field in REQUIRED_FIELDS:
            if field not in rec:
                errors.append(f"{loc}: missing required field '{field}'")
        if 'Semantics' in rec and not rec['Semantics'].strip():
            errors.append(f"{loc}: empty Semantics")

        # 2. Tag is well formed for this registry, and unique by its parsed value
        #    ("0.1" and "0.01" are the same CoAP code, "04" and "4" the same integer)
        try:
            key = registry.parse_tag(fname, tag)
        except (ValueError, KeyError):
            errors.append(f"{loc}: malformed Tag for {fname}")
            key = tag
        if key in seen_tags:
            errors.append(f"{loc}: duplicate Tag (first seen at record {seen_tags[key]})")
        else:
            seen_tags[key] = i

        words = rec.get('Words', '').strip()
        source = rec.get('Source', '').strip()
        semantics = rec.get('Semantics', '').strip()

        # 3. Source valid
        if source not in VALID_SOURCES:
            errors.append(f"{loc}: invalid Source={source!r} (must be one of {sorted(VALID_SOURCES)})")

        # 4. HTML entities (issue #9 regression guard)
        for field_name, value in (('Semantics', semantics), ('Words', words)):
            m = HTML_ENTITY_RE.search(value)
            if m:
                errors.append(f"{loc}: HTML entity {m.group()!r} found in {field_name} (issue #9 regression)")

        if source == 'skip':
            continue

        # 5. Blocks on needs-manual / new / empty Words
        if source in ('needs-manual', 'new'):
            errors.append(f"{loc}: Source={source!r} — manual Words required before generate")
        elif not words:
            errors.append(f"{loc}: empty Words field")

        if words:
            # 6. Valid C identifier tokens
            for token in words.split():
                if not TOKEN_RE.match(token):
                    errors.append(f"{loc}: token {token!r} in Words is not a valid identifier token ([a-z0-9_])")

            # 7. Duplicate Words inside one generated enum
            scoped = (registry.words_scope(fname, tag), words)
            if scoped in seen_words:
                errors.append(
                    f"{loc}: Words={words!r} duplicates Tag={seen_words[scoped]!r} "
                    f"(would produce duplicate C enum name)"
                )
            else:
                seen_words[scoped] = tag

    return errors


def main():
    if not os.path.isdir(db_dir):
        print(f"ERROR: db/ directory not found at {db_dir}", file=sys.stderr)
        sys.exit(1)

    all_errors = []
    for fname in sorted(os.listdir(db_dir)):
        if not fname.endswith('.rec'):
            continue
        errors = check_file(os.path.join(db_dir, fname))
        all_errors.extend(errors)

    if all_errors:
        print(f"check.py FAILED — {len(all_errors)} error(s):\n")
        for err in all_errors:
            print(f"  {err}")
        sys.exit(1)
    else:
        print("check.py OK — all db/*.rec files valid")


if __name__ == '__main__':
    main()
