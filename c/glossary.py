"""
glossary.py — explain the abbreviations used in a registry's generated names, for a comment in the header.

Three sources, each listed only for abbreviations that actually occur in the names:
- namespace prefixes (db/namespaces/<registry>.rec): 'UR' -> its Description, Organization and Spec
- acronyms whose expansion IANA itself gives: 'CBOR Web Token (CWT)' -> 'CWT: CBOR Web Token'
- word shortenings made by the naming rules (name.py): 'STRCT' -> 'structure', listed only where the
  entry's own IANA text contains the full word, so a token that is also a plain word is not mis-explained
"""

import collections
import re

import cbor_names_v2
import name
import namespaces
import recfile


def _named(db_file):
    return [r for r in recfile.read(db_file)
            if r.get('Words', '').strip() and r.get('Source', '').strip() not in ('skip', 'new', 'needs-manual')]


def entries(db_file):
    """Three sorted lists of (ABBREVIATION, explanation): namespace prefixes, acronyms, word shortenings.
    An explanation may have a second line (a namespace's spec link)."""
    records = _named(db_file)
    used = {token for r in records for token in r['Words'].split()}

    prefixes = []
    for ns in namespaces.load(db_file).values():
        if any(ns.has_prefix(r['Words']) for r in records):
            detail = ns.description + (f' ({ns.organization})' if ns.organization else '')
            prefixes.append(('_'.join(ns.prefix).upper(), detail + (f'\n{ns.spec}' if ns.spec else '')))

    acronyms = {}
    for r in records:
        semantics = ' '.join(r.get('Semantics', '').split())
        for match in re.finditer(r'((?:[\w-]+\s+){1,8})\(([A-Za-z][A-Za-z0-9]{1,7})\)', semantics):
            acronym = match.group(2)
            letters = sum(c.isupper() or c.isdigit() for c in acronym)
            words = match.group(1).split()[-letters:] if letters else []
            if acronym.lower() in used and letters >= 2 and cbor_names_v2._acronym_matches(acronym, words):
                acronyms.setdefault(acronym.upper(), ' '.join(words))

    expansions = collections.defaultdict(set)
    for full, short in {**name._VERY_COMMON_ABBREV, **name._LONG_ABBREV, **cbor_names_v2.ABBREVIATIONS}.items():
        if short != full:
            expansions[short].add(full)
    shortenings = collections.defaultdict(set)
    for r in records:
        text = set(re.findall(r'[a-z0-9]+', r.get('Semantics', '').lower()))
        for token in r['Words'].split():
            for full in expansions.get(token, ()):
                if full in text:
                    shortenings[token.upper()].add(full)

    return [sorted(prefixes),
            sorted((a, e) for a, e in acronyms.items() if a not in dict(prefixes)),
            sorted((short, ' / '.join(sorted(fulls))) for short, fulls in shortenings.items())]


def comment(db_file, indent='  '):
    """A C block comment explaining the abbreviations, or '' when the names use none."""
    groups = [group for group in entries(db_file) if group]
    if not groups:
        return ''
    width = max(len(abbreviation) for group in groups for abbreviation, _ in group)
    lines = [f'{indent}/* Abbreviations in these names:']
    for number, group in enumerate(groups):
        if number:
            lines.append(f'{indent} *')
        for abbreviation, explanation in group:
            first, *more = explanation.replace('*/', '* /').split('\n')  # '*/' would end the comment early
            lines.append(f'{indent} *   {abbreviation.ljust(width)}  {first}')
            lines += [f'{indent} *   {"".ljust(width)}  {line}' for line in more]
    lines.append(f'{indent} */')
    return '\n'.join(lines) + '\n'
