#!/usr/bin/env python3
"""
check.py — validate db/*.rec integrity before generate.

Exits non-zero on any failure, printing ALL errors (not just first).
"""

import os
import re
import sys

import recfile

script_dir = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(os.path.dirname(script_dir), 'db')

VALID_SOURCES = {'heuristic', 'llm', 'manual', 'needs-manual', 'new'}
REQUIRED_FIELDS = {'Tag', 'Words', 'Semantics', 'Reference', 'Source'}
HTML_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#\d+;')
TOKEN_RE = re.compile(r'^[a-z0-9_]+$')


def check_file(db_file):
    errors = []
    fname = os.path.basename(db_file)
    records = recfile.read(db_file)

    seen_tags = {}    # tag -> first record index
    seen_words = {}   # words -> first tag

    for i, rec in enumerate(records):
        tag = rec.get('Tag', '').strip()
        loc = f"{fname} Tag={tag!r}"

        # 1. Required fields
        for field in REQUIRED_FIELDS:
            if field not in rec:
                errors.append(f"{loc}: missing required field '{field}'")

        # 2. Duplicate Tag keys
        if tag in seen_tags:
            errors.append(f"{loc}: duplicate Tag (first seen at record {seen_tags[tag]})")
        else:
            seen_tags[tag] = i

        words = rec.get('Words', '').strip()
        source = rec.get('Source', '').strip()
        semantics = rec.get('Semantics', '').strip()

        # 3. Source valid
        if source not in VALID_SOURCES:
            errors.append(f"{loc}: invalid Source={source!r} (must be one of {sorted(VALID_SOURCES)})")

        # 4. Blocks on needs-manual / new / empty Words
        if source in ('needs-manual', 'new'):
            errors.append(f"{loc}: Source={source!r} — manual Words required before generate")
        elif not words:
            errors.append(f"{loc}: empty Words field")

        # 5. Valid C identifier tokens (only if words is non-empty)
        if words:
            for token in words.split():
                if not TOKEN_RE.match(token):
                    errors.append(f"{loc}: token {token!r} in Words is not a valid identifier token ([a-z0-9_])")

            # 6. Duplicate Words
            if words in seen_words:
                errors.append(
                    f"{loc}: Words={words!r} duplicates Tag={seen_words[words]!r} "
                    f"(would produce duplicate C enum name)"
                )
            else:
                seen_words[words] = tag

        # 7. No HTML entities in Semantics or Words
        for field_name, value in (('Semantics', semantics), ('Words', words)):
            m = HTML_ENTITY_RE.search(value)
            if m:
                errors.append(f"{loc}: HTML entity {m.group()!r} found in {field_name} (issue #9 regression)")

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
        print(f"check.py OK — all db/*.rec files valid")


if __name__ == '__main__':
    main()
