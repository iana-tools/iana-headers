#!/usr/bin/env python3
"""
name.py — fill Words on Source:new entries via per-registry rules (or LLM for CBOR tag text).

EXPERIMENTAL (--tfidf): when the rules find nothing for a CBOR tag, rank the words of its
Semantics by how rare they are across the Semantics already in db/ and keep the top few.

Collision rule: if two or more new entries would produce the same candidate
Words, ALL of them keep Words empty and are reported for manual resolution.

Each registry has its own namer because the published C identifiers were
historically derived from different columns with different rules (e.g. CoAP
codes are prefixed by their class, HTTP field names come from the Tag, CoAP
content formats get their media type parameters folded into the name).
Changing a rule here renames public identifiers for NEW entries only; existing
db records keep their committed Words.
"""

import os
import re
import sys
import math
import argparse

import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')


# ---------------------------------------------------------------------------
# Plain registries (CBOR simple values, CoAP options, HTTP status codes, ...)
# Rule: drop a trailing " (comment)", every non [A-Za-z0-9] character separates words.
# ---------------------------------------------------------------------------

def _plain_tokens(text):
    text = re.sub(r'\s+\(.*\)', '', text)
    return [t.lower() for t in re.sub(r'[^a-zA-Z0-9_]', '_', text).split('_') if t]


def plain_words(rec):
    return ' '.join(_plain_tokens(rec.get('Semantics', '')))


def http_field_words(rec):
    tag = rec.get('Tag', '')
    if '*' in tag:
        return 'wildcard'
    return ' '.join(_plain_tokens(tag))


def coap_code_words(rec):
    """'4.04' + 'Not Found' -> 'client error not found' (class label is part of the identifier)."""
    try:
        label = registry.coap_class_label(rec.get('Tag', ''))
    except (ValueError, KeyError):
        return ''
    return ' '.join(label.lower().split() + _plain_tokens(rec.get('Semantics', '')))


def signaling_option_words(rec):
    """'+' reads as 'as' ('a+b' -> 'a as b'), same as content formats."""
    text = re.sub(r'\s+\(.*\)', '', rec.get('Semantics', ''))
    text = text.replace('+', '_AS_')
    return ' '.join(t.lower() for t in re.sub(r'[^a-zA-Z0-9_]', '_', text).split('_') if t)


def content_format_words(rec):
    """Media type (plus optional '; coding') -> words; parameters are folded into the name."""
    s = re.sub(r'\s+\(.*\)', '', rec.get('Semantics', ''))
    # Specific handling of known extra parameters
    s = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); cose-type="cose-([^"]+)"', r'\1_\2_\3', s)
    # General handling of unknown parameters
    s = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); *(?:[a-zA-Z0-9\-_]+)="([^"]+)"', r'\1_\2_\3', s)
    s = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); *(?:[a-zA-Z0-9\-_]+)=([^"]+)', r'\1_\2_\3', s)
    # '+' is a close semantic approximation of 'as' (image/svg+xml -> IMAGE_SVG_AS_XML)
    s = s.replace('+', '_AS_')
    return ' '.join(t.lower() for t in re.sub(r'[^a-zA-Z0-9_]', '_', s).split('_') if t)


# ---------------------------------------------------------------------------
# CBOR tag semantics: free text -> short words (heuristic)
# Faithful port of the original c_header_cbor.py rules; the db freezes the result.
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
_CBOR_BOILERPLATE_PREFIXES = (
    "A CBOR tag that contains a ",
    "A CBOR tag that contains an ",
    "A CBOR tag that contains either ",
)


def _clean(s):
    s = re.sub(r'[.,].* defined in .*', '', s)
    return s


def _strip_brackets(original, s):
    """A description that is entirely wrapped in [...] or (...) keeps its content."""
    if original and ((original[0] == '[' and original[-1] == ']') or (original[0] == '(' and original[-1] == ')')):
        return s[1:-1]
    return s


def cbor_text_words(semantics):
    """Return lowercase space separated words for a CBOR tag semantics string ('' if none)."""
    s = semantics
    for pfx in _CBOR_BOILERPLATE_PREFIXES:
        if s.startswith(pfx):
            s = s[len(pfx):]
            break

    original = s
    s = _clean(s)
    s = _strip_brackets(original, s)
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'\[.*?\]', '', s)
    s = re.sub(r'[()\[\]]', ' ', s).strip()

    # Drop a description after ':' unless the colon is glued to a word ("ur:digest") or starts a URI ("https://")
    s = re.split(r'\s*:(?!\w|//)\s*', s, maxsplit=1)[0].strip()
    s = s.split(';', 1)[0].strip()
    idx = s.find('. ')
    if idx != -1:
        s = s[:idx]

    s = re.sub(r'[_\-]', ' ', s)

    words = [w.replace('+', 'PLUS').strip('_') for w in s.split()]
    if words and words[0] == 'A':
        words = words[1:]
    words = [part for w in words for part in re.sub(r'\W+', ' ', w).split()]

    words = [_VERY_COMMON_ABBREV.get(w.lower(), w) for w in words]
    if sum(len(w) for w in words) >= 40:
        words = [_LONG_ABBREV.get(w.lower(), w) for w in words]
        words = [w for w in words if w.lower() not in _STOPWORDS]

    return ' '.join(w.lower() for w in words)


def cbor_tag_words(rec):
    return cbor_text_words(rec.get('Semantics', ''))


# Kept for callers that only have the text
def heuristic_words(semantics, tag_hint=''):
    return cbor_text_words(semantics)


NAMERS = {
    'cbor_tags.rec': cbor_tag_words,
    'cbor_simple_values.rec': plain_words,
    'coap_request_codes.rec': coap_code_words,
    'coap_response_codes.rec': coap_code_words,
    'coap_signaling_codes.rec': coap_code_words,
    'coap_options.rec': plain_words,
    'coap_content_formats.rec': content_format_words,
    'coap_signaling_option_numbers.rec': signaling_option_words,
    'http_status_codes.rec': plain_words,
    'http_field_names.rec': http_field_words,
}


# ---------------------------------------------------------------------------
# TF-IDF namer (experimental, --tfidf). Db driven, standard library only.
# ---------------------------------------------------------------------------

def _raw_tokens(text):
    """Words of a CBOR tag description: same cuts as cbor_text_words, but no abbreviations or stopwords."""
    text = re.sub(r'\w[\w+.-]*://\S*', '', text)          # URIs
    text = re.sub(r'\(.*?\)|\[.*?\]', '', text)         # parentheticals
    text = re.split(r'\s*:(?!\w|//)\s*', text, maxsplit=1)[0].split(';', 1)[0]
    return [w.lower() for w in re.sub(r'\W+', ' ', text.replace('_', ' ')).split()]


def tfidf_words(semantics, corpus_token_sets, max_tokens=5):
    """Keep the `max_tokens` rarest words of `semantics` (in their original order).

    corpus_token_sets: one set of words per description already in the db. Words that appear in
    many descriptions (the, of, type, value) score low; rare technical words (base64url, corim) high.
    Returns '' if the text has no words.
    """
    tokens = _raw_tokens(semantics)
    if not tokens:
        return ''
    n = len(corpus_token_sets) + 1
    idf = {t: math.log(n / (sum(1 for doc in corpus_token_sets if t in doc) + 1)) for t in set(tokens)}
    first_seen = {}
    for i, t in enumerate(tokens):
        first_seen.setdefault(t, i)
    keep = sorted(first_seen, key=lambda t: (-idf[t], first_seen[t]))[:max_tokens]
    return ' '.join(sorted(keep, key=first_seen.get))


# ---------------------------------------------------------------------------
# LLM namer (optional — falls back silently). Only used for free-text CBOR tag semantics.
# ---------------------------------------------------------------------------

def llm_words(semantics, existing_examples, fallback_fn):
    import http.client
    import json
    import urllib.request
    try:
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
    except (OSError, ValueError, http.client.HTTPException):
        return fallback_fn(semantics)


# ---------------------------------------------------------------------------
# Core naming logic
# ---------------------------------------------------------------------------

def fill_words_for_file(db_file, use_llm=False, use_tfidf=False, dry_run=False):
    records = recfile.read(db_file)

    for r in records:  # keys must match what _apply_assignments sees after stripping
        r['Tag'] = r.get('Tag', '').strip()
    new_entries = [r for r in records if r.get('Source', '').strip() == 'new']
    if not new_entries:
        return []

    fname = os.path.basename(db_file)
    namer = NAMERS.get(fname, cbor_tag_words)

    def scoped(rec, words):
        # Words only need to be unique within one generated C enum
        return (registry.words_scope(fname, rec.get('Tag', '')), words)

    existing_words = {scoped(r, r.get('Words', '').strip()) for r in records
                      if r.get('Source', '') not in ('new', 'skip') and r.get('Words', '').strip()}

    # Few-shot examples for LLM from existing named records
    examples = [
        (r['Semantics'], r['Words'])
        for r in records
        if r.get('Source', '') not in ('new', '') and r.get('Words', '').strip() and r.get('Semantics', '').strip()
    ]

    # Generate candidates for all new entries
    candidates = {}
    sources = {}
    corpus = None  # built on first use by --tfidf
    for rec in new_entries:
        tag = rec['Tag']
        if use_llm and namer is cbor_tag_words:
            candidates[tag] = llm_words(rec.get('Semantics', ''), examples, cbor_text_words)
            sources[tag] = 'llm'
        else:
            candidates[tag] = namer(rec)
            sources[tag] = 'heuristic'
        if use_tfidf and namer is cbor_tag_words and not candidates[tag]:
            if corpus is None:
                corpus = [set(_raw_tokens(r['Semantics'])) for r in records
                          if r.get('Semantics') and r.get('Source', '') not in ('new', 'skip')]
            candidates[tag] = tfidf_words(rec.get('Semantics', ''), corpus)

    # Collision detection: count how many times each candidate appears (per enum scope)
    from collections import Counter
    rec_by_tag = {r['Tag']: r for r in new_entries}
    key = {tag: scoped(rec_by_tag[tag], cand) for tag, cand in candidates.items()}
    candidate_counts = Counter(key[tag] for tag, cand in candidates.items() if cand)

    # Also check against existing db Words
    collision_with_existing = {tag for tag, cand in candidates.items() if cand and key[tag] in existing_words}

    # Group new-vs-new collisions
    collision_groups = {}  # candidate -> [tags]
    for tag, cand in candidates.items():
        if cand and candidate_counts[key[tag]] > 1:
            group = cand if not key[tag][0] else f'{cand} [{key[tag][0]}]'
            collision_groups.setdefault(group, []).append(tag)

    # Determine which tags are valid vs need-manual
    colliding_tags = set()
    for tags in collision_groups.values():
        colliding_tags.update(tags)
    colliding_tags.update(collision_with_existing)

    # Build rewrite map: tag -> (new Words, Source). Empty Words means needs-manual.
    assignments = {}
    for tag, cand in candidates.items():
        if tag in colliding_tags or not cand:
            assignments[tag] = ('', 'needs-manual')
        else:
            assignments[tag] = (cand, sources[tag])

    if not dry_run:
        _apply_assignments(db_file, assignments)

    return _report(new_entries, collision_groups, collision_with_existing, candidates)


def _apply_assignments(db_file, assignments):
    """Rewrite db_file, updating Words/Source for the Source:new entries named in assignments."""
    with open(db_file, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    lines = []
    current_tag = None
    for line in raw_lines:
        # Tolerate editors that strip trailing whitespace ("Words: " -> "Words:") or leave some
        stripped = line.rstrip()

        if stripped.startswith('Tag:'):
            current_tag = stripped[4:].strip()
            lines.append(line)
        elif stripped.startswith('Words:') and current_tag in assignments:
            lines.append(f'Words: {assignments[current_tag][0]}\n')
        elif stripped.replace(' ', '') == 'Source:new' and current_tag in assignments:
            lines.append(f'Source: {assignments[current_tag][1]}\n')
        else:
            lines.append(line)

    with open(db_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def _report(new_entries, collision_groups, collision_with_existing, candidates):
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

    # Entries the namer could not name at all
    for rec in new_entries:
        if not candidates.get(rec['Tag']):
            issues.append(f"  UNNAMEABLE Tag {rec['Tag']}: {rec.get('Semantics', '')!r} — no words produced")

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Fill Words on Source:new db entries')
    parser.add_argument('--tfidf', action='store_true', help='Experimental: for CBOR tags the rules cannot name, keep the rarest words of the description')
    parser.add_argument('--llm', action='store_true', help='Use local Ollama LLM for CBOR tag text (falls back to the rules)')
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
        issues = fill_words_for_file(db_file, use_llm=args.llm, use_tfidf=args.tfidf, dry_run=args.dry_run)
        if issues:
            print(f"\n{fname}:")
            for iss in issues:
                print(iss)
            all_issues.extend(issues)

    if all_issues:
        print(f"\n{'='*60}")
        print(f"{len(all_issues)} entr(ies) need manual Words — edit db/*.rec (set Source: manual) then run `make check`.")
        if not args.dry_run:
            sys.exit(1)
    else:
        print("All new entries named successfully." + (" (dry-run)" if args.dry_run else ""))


if __name__ == '__main__':
    main()
