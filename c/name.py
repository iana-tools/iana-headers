#!/usr/bin/env python3
"""
name.py — fill Words on Source:new entries via heuristic (or LLM).

Collision rule: if two or more new entries would produce the same candidate
Words, ALL of them keep Words empty and are reported for manual resolution.
"""

import os
import re
import sys
import argparse
import toml

import recfile

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')


# ---------------------------------------------------------------------------
# Heuristic word-token generators
# (ported from existing c_header_cbor.py / c_header_http.py / c_header_coap.py)
# Output: lowercase space-separated tokens  e.g. "date time string"
# Style (SCREAMING_SNAKE, PascalCase …) is applied later by generate.py
# ---------------------------------------------------------------------------

_VERY_COMMON_ABBREV = {
    "standard": "std", "identifier": "id", "message": "msg",
    "configuration": "config", "reference": "ref", "referenced": "ref",
    "previously": "prev",
}
_LONG_ABBREV = {
    "number": "num", "complex": "cplx", "index": "idx", "attribute": "attr",
    "maximum": "max", "minimum": "min", "communication": "comm",
    "protocol": "proto", "information": "info", "authentication": "auth",
    "representation": "repr", "algorithm": "algo", "version": "ver",
    "encoding": "enc", "arguments": "arg", "object": "obj", "language": "lang",
    "independent": "indep", "alternatives": "alt", "text": "txt",
    "string": "str", "integer": "int", "signal": "sig", "channel": "chn",
    "structure": "strct", "structures": "strct", "attestation": "attest",
    "identify": "ident", "geographic": "geo", "geographical": "geo",
    "coordinate": "coord", "included": "inc", "value": "val",
    "values": "vals", "record": "rec", "report": "rpt", "definition": "def",
    "addressed": "addr", "capabilities": "cap", "additional": "add",
    "operation": "op", "operations": "op", "level": "lvl", "levels": "lvls",
    "encode": "enc", "encoded": "enc", "component": "comp",
    "condition": "cond", "database": "db", "element": "elem",
    "environment": "env", "parameter": "param", "variable": "var",
    "variables": "var", "resource": "res", "exception": "excpt",
    "instance": "inst", "organization": "org", "response": "resp",
    "security": "sec",
}
_STOPWORDS = {"algorithm", "and", "to", "a", "from", "the", "bare"}


def _clean(s):
    s = re.sub(r'[.,].* defined in .*', '', s)
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'\[.*?\]', '', s)
    s = re.sub(r'[()[\]]', ' ', s)
    return s.strip()


def _tokenise(s):
    """Return a list of lowercase word tokens from a semantics string."""
    # Strip boilerplate CBOR prefix variants
    for pfx in ("A CBOR tag that contains either ", "A CBOR tag that contains an ",
                 "A CBOR tag that contains a ", "A CBOR tag that contains "):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break

    s = _clean(s)

    # Truncate at first ':' (not part of URI), ';', or '. '
    s = re.split(r'(?<!://)(?<!\w:)\s*:\s*(?!\w)', s)[0].strip()
    s = s.split(';', 1)[0].strip()
    idx = s.find('. ')
    if idx != -1:
        s = s[:idx]

    s = re.sub(r'[_\-]', ' ', s)

    words = []
    for chunk in s.split():
        chunk = re.sub(r'\W+', '', chunk)
        if chunk:
            words.append(chunk.lower())

    if words and words[0] == 'a':
        words = words[1:]

    words = [_VERY_COMMON_ABBREV.get(w, w) for w in words]

    if sum(len(w) for w in words) >= 40:
        words = [_LONG_ABBREV.get(w, w) for w in words]
        words = [w for w in words if w not in _STOPWORDS]

    return words


def heuristic_words(semantics, tag_hint=''):
    """Return lowercase token string from semantics, e.g. 'date time string'."""
    tokens = _tokenise(semantics)
    if not tokens:
        return ''
    return ' '.join(tokens)


# ---------------------------------------------------------------------------
# LLM namer (optional — falls back silently)
# ---------------------------------------------------------------------------

def llm_words(semantics, existing_examples, fallback_fn):
    try:
        import urllib.request, json
        examples_text = '\n'.join(
            f'  Semantics: "{sem}" -> Words: "{words}"'
            for sem, words in existing_examples[:10]
        )
        prompt = (
            "You generate short lowercase word tokens for IANA registry entries. "
            "Tokens are space-separated, no punctuation, 1-6 words max.\n"
            f"Examples:\n{examples_text}\n"
            f'Now produce Words for: Semantics: "{semantics}"\n'
            "Respond with only the token string, nothing else."
        )
        payload = json.dumps({
            "model": "qwen2.5:1.5b",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }).encode()
        req = urllib.request.Request(
            'http://localhost:11434/api/generate',
            data=payload,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            tokens = result.get('response', '').strip().lower()
            tokens = re.sub(r'[^a-z0-9 ]', ' ', tokens).split()
            return ' '.join(tokens) if tokens else fallback_fn(semantics)
    except Exception:
        return fallback_fn(semantics)


# ---------------------------------------------------------------------------
# Core naming logic
# ---------------------------------------------------------------------------

def fill_words_for_file(db_file, use_llm=False, dry_run=False):
    records = recfile.read(db_file)

    new_entries = [r for r in records if r.get('Source', '') == 'new']
    if not new_entries:
        return []

    existing_words = {r.get('Words', '').strip() for r in records if r.get('Source', '') != 'new' and r.get('Words', '').strip()}

    # Few-shot examples for LLM from existing named records
    examples = [
        (r['Semantics'], r['Words'])
        for r in records
        if r.get('Source', '') not in ('new', '') and r.get('Words', '').strip() and r.get('Semantics', '').strip()
    ]

    # Generate candidates for all new entries
    candidates = {}
    for rec in new_entries:
        tag = rec['Tag']
        sem = rec.get('Semantics', '')
        if use_llm:
            candidate = llm_words(sem, examples, heuristic_words)
        else:
            candidate = heuristic_words(sem, tag_hint=tag)
        candidates[tag] = candidate

    # Collision detection: count how many times each candidate appears
    from collections import Counter
    candidate_counts = Counter(c for c in candidates.values() if c)

    # Also check against existing db Words
    collision_with_existing = {tag for tag, cand in candidates.items() if cand and cand in existing_words}

    # Group new-vs-new collisions
    collision_groups = {}  # candidate -> [tags]
    for tag, cand in candidates.items():
        if cand and candidate_counts[cand] > 1:
            collision_groups.setdefault(cand, []).append(tag)

    # Determine which tags are valid vs need-manual
    colliding_tags = set()
    for tags in collision_groups.values():
        colliding_tags.update(tags)
    colliding_tags.update(collision_with_existing)

    # Build rewrite map: tag -> new Words (empty string = needs-manual)
    assignments = {}
    for tag, cand in candidates.items():
        if tag in colliding_tags or not cand:
            assignments[tag] = ''
        else:
            assignments[tag] = cand

    if dry_run:
        return _report(new_entries, assignments, collision_groups, collision_with_existing, candidates, dry_run=True)

    # Rewrite the rec file in-place
    _apply_assignments(db_file, assignments)

    return _report(new_entries, assignments, collision_groups, collision_with_existing, candidates)


def _apply_assignments(db_file, assignments):
    """Rewrite db_file, updating Words/Source for entries in assignments."""
    lines = []
    with open(db_file, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    # Parse line-by-line, tracking current record's Tag
    current_tag = None
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.rstrip('\n')

        if stripped.startswith('Tag: '):
            current_tag = stripped[5:].strip()
            lines.append(line)
        elif stripped.startswith('Words: ') and current_tag in assignments:
            words = assignments[current_tag]
            lines.append(f'Words: {words}\n')
        elif stripped.startswith('Source: new') and current_tag in assignments:
            words = assignments.get(current_tag, '')
            source = 'needs-manual' if not words else 'heuristic'
            lines.append(f'Source: {source}\n')
        else:
            lines.append(line)
        i += 1

    with open(db_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def _report(new_entries, assignments, collision_groups, collision_with_existing, candidates, dry_run=False):
    issues = []

    # Report intra-run collisions
    for cand, tags in sorted(collision_groups.items()):
        entries_info = []
        for t in tags:
            sem = next((r.get('Semantics', '') for r in new_entries if r['Tag'] == t), '')
            entries_info.append(f"    Tag {t}: {sem!r}")
        issues.append(
            f"  COLLISION (new-vs-new) candidate={cand!r} — all left empty:\n" +
            '\n'.join(entries_info)
        )

    # Report collisions with existing
    for tag in sorted(collision_with_existing):
        sem = next((r.get('Semantics', '') for r in new_entries if r['Tag'] == tag), '')
        cand = candidates.get(tag, '')
        issues.append(
            f"  COLLISION (new-vs-existing) Tag {tag}: candidate={cand!r} collides with existing record\n"
            f"    Semantics: {sem!r}"
        )

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Fill Words on Source:new db entries')
    parser.add_argument('--llm', action='store_true', help='Use local Ollama LLM (falls back to heuristic)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be written without modifying files')
    args = parser.parse_args()

    if not os.path.isdir(db_dir):
        print(f"ERROR: db/ directory not found at {db_dir}. Run sync.py first.", file=sys.stderr)
        sys.exit(1)

    all_issues = []
    for fname in sorted(os.listdir(db_dir)):
        if not fname.endswith('.rec'):
            continue
        db_file = os.path.join(db_dir, fname)
        issues = fill_words_for_file(db_file, use_llm=args.llm, dry_run=args.dry_run)
        if issues:
            print(f"\n{fname}:")
            for iss in issues:
                print(iss)
            all_issues.extend(issues)

    if all_issues:
        print(f"\n{'='*60}")
        print(f"{len(all_issues)} collision(s) require manual Words — edit db/*.rec then run `make check`.")
        sys.exit(1)
    else:
        print("All new entries named successfully." + (" (dry-run)" if args.dry_run else ""))


if __name__ == '__main__':
    main()
