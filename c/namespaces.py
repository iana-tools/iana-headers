#!/usr/bin/env python3
"""
namespaces.py — families of registry entries that share a name prefix (db/namespaces/<registry>.rec).

A namespace record says which organisation or scheme a family belongs to, the Prefix its names start with,
and how to recognise its entries: a `Semantics Match` and/or `Reference Match` regular expression. A named
group `label` in the Semantics rule captures the entry's own name from the IANA text ("ur:seed" -> "seed").

Used by sync (new records get `Namespace:`), name.py and cbor_names_v2.py (names start with the prefix,
which never repeats in the rest of the name) and check.py (assignment and prefix are enforced).
`python3 namespaces.py --assign` adds the field to existing records after the table changes.
"""

import argparse
import os
import re
import sys

import recfile

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')
namespaces_dir = os.path.join(db_dir, 'namespaces')

REQUIRED = ('Namespace', 'Prefix', 'Organization', 'Description')
RULES = ('Semantics Match', 'Reference Match')
TOKEN_RE = re.compile(r'^[a-z0-9_]+$')


class Namespace:
    def __init__(self, record):
        self.name = record.get('Namespace', '').strip()
        self.prefix = record.get('Prefix', '').split()
        self.organization = record.get('Organization', '').strip()
        self.description = record.get('Description', '').strip()
        self.spec = record.get('Spec', '').strip()
        self.semantics_rule = re.compile(record['Semantics Match']) if record.get('Semantics Match') else None
        self.reference_rule = re.compile(record['Reference Match']) if record.get('Reference Match') else None

    def matches(self, rec):
        semantics = ' '.join(rec.get('Semantics', '').split())
        return bool((self.semantics_rule and self.semantics_rule.search(semantics))
                    or (self.reference_rule and self.reference_rule.search(rec.get('Reference', ''))))

    def label(self, rec):
        """The entry's own name from the IANA text, if the rule captures one ('ur:ssh-public' -> 'ssh-public')."""
        match = self.semantics_rule.search(' '.join(rec.get('Semantics', '').split())) if self.semantics_rule else None
        return match.group('label') if match and 'label' in match.groupdict() else ''

    def apply(self, words):
        """'seed' -> 'ur seed'; 'cose cose sign1' or 'sign1' -> 'cose sign1'. Words are lowercase tokens."""
        tokens = words.split()
        while tokens[:len(self.prefix)] == self.prefix:
            tokens = tokens[len(self.prefix):]
        return ' '.join(self.prefix + tokens) if tokens else ''

    def has_prefix(self, words):
        return words.split()[:len(self.prefix)] == self.prefix


def table_path(db_file):
    return os.path.join(namespaces_dir, os.path.basename(db_file))


def load(db_file):
    """{name: Namespace} for the registry of db_file; {} when it has no namespace table."""
    path = table_path(db_file)
    return {ns.name: ns for ns in (Namespace(r) for r in recfile.read(path))} if os.path.exists(path) else {}


def validate(db_file):
    """Errors in the namespace table of db_file's registry."""
    errors, seen = [], set()
    path = table_path(db_file)
    if not os.path.exists(path):
        return errors
    where = os.path.relpath(path, repo_dir)
    for record in recfile.read(path):
        name = record.get('Namespace', '').strip()
        loc = f"{where} Namespace={name!r}"
        for field in REQUIRED:
            if not record.get(field, '').strip():
                errors.append(f"{loc}: missing {field}")
        if name in seen:
            errors.append(f"{loc}: duplicate Namespace")
        seen.add(name)
        if not all(TOKEN_RE.match(token) for token in record.get('Prefix', '').split()):
            errors.append(f"{loc}: Prefix must be lowercase [a-z0-9_] words")
        if not any(record.get(rule, '').strip() for rule in RULES):
            errors.append(f"{loc}: needs a Semantics Match or Reference Match rule")
        for rule in RULES:
            try:
                re.compile(record.get(rule, ''))
            except re.error as e:
                errors.append(f"{loc}: {rule} is not a valid regular expression ({e})")
    return errors


def detect(rec, table):
    """Names of the namespaces whose rules match rec."""
    return [ns.name for ns in table.values() if ns.matches(rec)]


def assign(db_file, dry_run=False):
    """Add `Namespace:` to records that a rule matches but that do not have it yet; return the tags changed."""
    import sync  # sync imports this module; keep the dependency one-way at import time
    table = load(db_file)
    changed = []
    for rec in recfile.read(db_file):
        if rec.get('Namespace', '').strip() or not rec.get('Tag', '').strip():
            continue
        found = detect(rec, table)
        if len(found) == 1:
            changed.append((rec['Tag'].strip(), found[0]))
            if not dry_run:
                sync._set_record_field(db_file, rec['Tag'].strip(), 'Namespace', found[0])
    return changed


def main():
    parser = argparse.ArgumentParser(description='Assign namespaces from db/namespaces/*.rec to db records')
    parser.add_argument('--assign', action='store_true', help='add Namespace to matching records that lack it')
    parser.add_argument('--dry-run', action='store_true', help='with --assign: only list what would change')
    args = parser.parse_args()

    for fname in sorted(os.listdir(namespaces_dir)) if os.path.isdir(namespaces_dir) else []:
        db_file = os.path.join(db_dir, fname)
        errors = validate(db_file)
        if errors:
            print('\n'.join(errors), file=sys.stderr)
            sys.exit(1)
        table = load(db_file)
        print(f"{fname}: {len(table)} namespaces: {', '.join(table)}")
        if args.assign:
            changed = assign(db_file, dry_run=args.dry_run)
            verb = 'would assign' if args.dry_run else 'assigned'
            for tag, name in changed:
                print(f"  {verb} Tag {tag}: {name}")
            print(f"  {len(changed)} record(s) {verb}")


if __name__ == '__main__':
    main()
