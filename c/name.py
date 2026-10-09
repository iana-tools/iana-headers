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

import toml

import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')
_review_quit_requested = False


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
_CBOR_TAG_WORD_OVERRIDES = {
    '65535': 'invalid 16bit',
    '4294967295': 'invalid 32bit',
    '18446744073709551615': 'invalid 64bit',
}
_CBOR_TAG_WORD_SKIPS = {'554', '555'}


def _clean(s):
    s = re.sub(r'\s+as defined in\b.*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\(\s*[−-]\s*NaN\b', '(negative NaN', s, flags=re.IGNORECASE)
    s = re.sub(r'\(\s*\+\s*NaN\b', '(positive NaN', s, flags=re.IGNORECASE)
    s = re.sub(r'\bBoth NaNs signal\b', 'Both NaN signals', s, flags=re.IGNORECASE)
    s = re.sub(r'(?i)(Logical operator:\s*NONE)\s*/\s*(NOT)', r'\1 or \2', s)
    s = re.sub(r'(?i)\b(Logical operator):\s*', r'\1 ', s)
    s = re.sub(r'^A CBOR tag that contains(?: either| an| a)?\b\s*:?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:The\s+)?tagged CBOR (?:array|map|item) (?:containing|that contains)(?: an?\b)?\s*', '',
               s, flags=re.IGNORECASE)
    s = re.sub(r'^.*?\bindicates that the payload is(?: an?\b)?\s*', '', s, flags=re.IGNORECASE)
    return s


def cbor_text_words(semantics):
    """Return lowercase space separated words for a CBOR tag semantics string ('' if none)."""
    s = semantics.strip()
    if s and ((s[0] == '[' and s[-1] == ']') or (s[0] == '(' and s[-1] == ')')):
        s = s[1:-1]
    s = _clean(s)
    s = re.sub(r'\[[^\]]*\]', '', s)
    s = re.sub(r'\((?:RFC|draft|section)\b[^)]*\)', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[()\[\]]', ' ', s).strip()

    # Drop a description after ':' unless the colon is glued to a word ("ur:digest") or starts a URI ("https://")
    s = re.split(r'\s*:(?!\w|//)\s*', s, maxsplit=1)[0].strip()
    s = s.split(';', 1)[0].strip()
    idx = s.find('. ')
    if idx != -1:
        s = s[:idx]

    s = re.sub(r'[_\-]', ' ', s)

    words = [w.replace('+', 'PLUS').strip('_') for w in s.split()]
    if words and words[0].lower() in ('a', 'an', 'the'):
        words = words[1:]
    words = [part for w in words for part in re.sub(r'\W+', ' ', w).split()]

    words = [_VERY_COMMON_ABBREV.get(w.lower(), w) for w in words]
    if sum(len(w) for w in words) >= 40:
        words = [_LONG_ABBREV.get(w.lower(), w) for w in words]
        words = [w for w in words if w.lower() not in _STOPWORDS]

    return ' '.join(w.lower() for w in words)


# A suggestion longer than this is a sentence, not a name: a human should pick the name.
CBOR_TAG_MAX_WORDS = 10
# Words that describe a CBOR data item's type; a Data Item made only of other words is a name.
_CBOR_TYPE_WORDS = {
    'any', 'array', 'arrays', 'bigint', 'bool', 'boolean', 'byte', 'bytes', 'bstr', 'cbor', 'data', 'exactly',
    'float', 'int', 'integer', 'item', 'items', 'map', 'multiple', 'negative', 'null', 'number', 'or',
    'sequence', 'simple', 'string', 'strings', 'tag', 'tagged', 'text', 'tstr', 'uint', 'undefined',
    'unsigned', 'value',
}


def data_item_name(data_item):
    """'Proof of Process Packet (PPPP)' -> 'Proof of Process Packet'; '' for a type such as 'byte string'."""
    text = re.sub(r'\s*\([A-Z0-9]+\)\s*$', '', ' '.join(data_item.split()))
    tokens = re.findall(r'[A-Za-z0-9]+', text)
    if len(tokens) < 2 or sum(t[0].isupper() for t in tokens) < 2:
        return ''
    if any(t.lower() in _CBOR_TYPE_WORDS or t.isdigit() for t in tokens):
        return ''
    return text


def cbor_tag_words(rec):
    tag = rec.get('Tag', '').strip()
    if tag in _CBOR_TAG_WORD_SKIPS:
        return ''
    if tag in _CBOR_TAG_WORD_OVERRIDES:
        return _CBOR_TAG_WORD_OVERRIDES[tag]
    words = cbor_text_words(rec.get('Semantics', ''))
    if len(words.split()) <= CBOR_TAG_MAX_WORDS:
        return words
    # Some registrants put the item's name in the Data Item column and a paragraph in Semantics
    item_words = cbor_text_words(data_item_name(rec.get('Data Item', '')))
    return item_words if 0 < len(item_words.split()) <= CBOR_TAG_MAX_WORDS else ''


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

def fill_words_for_file(db_file, use_llm=False, use_tfidf=False, dry_run=False, interactive=False):
    records = recfile.read(db_file)

    for r in records:  # keys must match what _apply_assignments sees after stripping
        r['Tag'] = r.get('Tag', '').strip()
    pending_sources = ('new', 'needs-manual') if interactive else ('new',)
    new_entries = [r for r in records if r.get('Source', '').strip() in pending_sources]
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

    if interactive:
        return _review_candidates(db_file, new_entries, candidates, scoped, existing_words, dry_run, records)

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


# Enumerator prefix per db file in the default (non tiny_cbor) style, as configured in iana_settings.toml.
_ENUM_PREFIX_SETTINGS = {
    'cbor_tags.rec': ('cbor', 'tag_source'),
    'cbor_simple_values.rec': ('cbor', 'simple_value'),
    'coap_request_codes.rec': ('coap', 'request_response'),
    'coap_response_codes.rec': ('coap', 'request_response'),
    'coap_signaling_codes.rec': ('coap', 'request_response'),
    'coap_options.rec': ('coap', 'option'),
    'coap_content_formats.rec': ('coap', 'content_format'),
    'http_status_codes.rec': ('http', 'http_status_code'),
    'http_field_names.rec': ('http', 'http_field_name'),
}


def _enum_prefix(fname):
    """'cbor_tags.rec' -> 'CBOR_TAG_'; '…_' where the prefix depends on more than the file."""
    section = _ENUM_PREFIX_SETTINGS.get(fname)
    if section is None:  # signaling options get one enum per CoAP code
        return '…_'
    try:
        settings = toml.load(os.path.join(script_dir, 'iana_settings.toml'))
        return settings[section[0]][section[1]]['name'].upper() + '_'
    except (OSError, KeyError, toml.TomlDecodeError):
        return '…_'


def normalize_words(text):
    """'SUIT Report-Protected' -> 'suit report protected' (the form Words are stored in)."""
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text.lower()).split())


def _review_suggestions(fname, record, candidate):
    """Distinct (words, origin) choices for one record, best first."""
    options = [(candidate, 'suggested')]
    if fname == 'cbor_tags.rec':
        options.append((cbor_text_words(data_item_name(record.get('Data Item', ''))), 'from Data Item'))
        options.append((cbor_text_words(record.get('Semantics', '')), 'from Semantics, unshortened'))
    seen, out = set(), []
    for words, origin in options:
        if words and words not in seen:
            seen.add(words)
            out.append((words, origin))
    return out


# Function words and generic CBOR vocabulary carry no signal about which naming family a record belongs to
_SIMILARITY_IGNORED = _STOPWORDS | _CBOR_TYPE_WORDS | {
    'an', 'are', 'as', 'be', 'by', 'contains', 'for', 'in', 'into', 'is', 'it', 'its', 'of', 'on', 'that',
    'this', 'used', 'when', 'where', 'which', 'whose', 'with',
}


def _similar_names(record, named_records, limit=3):
    """Committed names whose Semantics share the most words with this record, to keep naming families consistent."""
    tokens = set(_raw_tokens(record.get('Semantics', ''))) - _SIMILARITY_IGNORED
    if not tokens:
        return []
    scored = []
    for other in named_records:
        other_tokens = set(_raw_tokens(other.get('Semantics', ''))) - _SIMILARITY_IGNORED
        shared = len(tokens & other_tokens)
        if shared:
            scored.append((shared / len(tokens | other_tokens), other['Tag'], other['Words'].strip()))
    scored.sort(key=lambda item: -item[0])
    return [(tag, words) for score, tag, words in scored[:limit] if score >= 0.2]


def _review_candidates(db_file, entries, candidates, scoped, existing_words, dry_run, records=()):
    global _review_quit_requested
    fname = os.path.basename(db_file)
    prefix = _enum_prefix(fname)
    named_records = [r for r in records
                     if r.get('Words', '').strip() and r.get('Source', '').strip() not in ('new', 'needs-manual', 'skip')]
    assignments = {}
    occupied_words = set(existing_words)
    pending = []
    tally = {'accepted': 0, 'edited': 0, 'skipped': 0}

    print(f"\n=== {fname}: {len(entries)} record(s) to review ===")
    for index, record in enumerate(entries):
        tag = record['Tag']
        print(f"\n[{index + 1}/{len(entries)}] {fname} Tag {tag}")
        if record.get('Data Item', '').strip():
            print(f"  IANA Data Item: {record['Data Item'].strip()}")
        print(f"  IANA Semantics: {record.get('Semantics', '')}")
        if record.get('Reference', '').strip():
            print(f"  Reference: {record['Reference'].strip()}")
        if record.get('Lifecycle', '').strip():
            print(f"  Lifecycle: {record['Lifecycle'].strip()} (name stays reviewable while IANA marks it so)")
        if record.get('Note', '').strip():
            print(f"  Note: {record['Note'].strip()}")

        options = []
        for words, origin in _review_suggestions(fname, record, candidates.get(tag, '')):
            flags = []
            if scoped(record, words) in occupied_words:
                flags.append('collides with an existing or already accepted name')
            if len(words.split()) > CBOR_TAG_MAX_WORDS:
                flags.append(f'{len(words.split())} words, consider shortening')
            options.append((words, origin, flags))
        if options:
            print('  Suggestions:')
            for number, (words, origin, flags) in enumerate(options, 1):
                marker = f'{number})' if 'collides' not in ' '.join(flags) else ' -'
                note = f"  !! {'; '.join(flags)}" if flags else ''
                print(f"    {marker} {words}  ->  {prefix}{'_'.join(words.split()).upper()}  ({origin}){note}")
        else:
            print('  Suggestions: (none: the description is too long or unclear to shorten automatically)')
        similar = _similar_names(record, named_records)
        if similar:
            print('  Similar existing names: ' + '; '.join(f'{words} (Tag {t})' for t, words in similar))

        selectable = [words for words, origin, flags in options if not any('collides' in f for f in flags)]
        decision = _prompt_name_decision(record, selectable, occupied_words, scoped, prefix)
        if decision is None:
            _review_quit_requested = True
            pending = entries[index:]
            break

        words, source, note = decision
        assignments[tag] = (words, source, note)
        if source == 'skip':
            tally['skipped'] += 1
        else:
            tally['accepted' if words in selectable else 'edited'] += 1
            occupied_words.add(scoped(record, words))

    if assignments and not dry_run:
        _apply_assignments(db_file, assignments)

    print(f"\n{fname}: {tally['accepted']} accepted, {tally['edited']} edited, {tally['skipped']} skipped"
          + (f", {len(pending)} left for later" if pending else ''))
    if pending:
        print(f"Review paused; {len(pending)} record(s) remain unchanged. Rerun `make review` to continue.")
        return [f"  REVIEW PENDING Tag {record['Tag']}" for record in pending]
    if dry_run and assignments:
        print('Dry run: review choices were not saved.')
    return []


def _prompt_name_decision(record, selectable, occupied_words, scoped, prefix=''):
    """Ask until the reviewer accepts a suggestion, enters a name, skips, or quits (None)."""
    while True:
        if len(selectable) > 1:
            accept = f'[a]ccept 1, [1-{len(selectable)}] pick, '
        elif selectable:
            accept = '[a]ccept, '
        else:
            accept = ''
        try:
            choice = input(f"  Choice ({accept}[e]dit, [s]kip, [q]uit): ").strip().lower()
        except EOFError:
            return None

        if choice in ('a', 'accept') and selectable:
            return selectable[0], 'manual', ''
        if choice.isdigit() and 1 <= int(choice) <= len(selectable):
            return selectable[int(choice) - 1], 'manual', ''
        if choice in ('e', 'edit'):
            try:
                typed = input('  Name (any case/punctuation; stored as lowercase words): ')
            except EOFError:
                return None
            words = normalize_words(typed)
            if not words:
                print('  Enter at least one letter or digit.')
                continue
            if scoped(record, words) in occupied_words:
                print('  That name is already used in this enum; choose a distinct name.')
                continue
            if words != typed.strip():
                print(f"  Saved as: {words}  ->  {prefix}{'_'.join(words.split()).upper()}")
            return words, 'manual', ''
        if choice in ('s', 'skip'):
            try:
                note = input('  Reason to skip this registration: ').strip()
            except EOFError:
                return None
            if not note:
                print('  Please enter a short reason so the exclusion is documented.')
                continue
            return '', 'skip', note
        if choice in ('q', 'quit'):
            return None
        print('  Choose one of the listed actions.')


def _apply_assignments(db_file, assignments):
    """Update Words/Source and optional Note fields without rewriting other record data."""
    with open(db_file, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    fields_by_tag = {}
    for tag, values in assignments.items():
        fields = {'Words': values[0], 'Source': values[1]}
        if len(values) > 2 and values[2]:
            fields['Note'] = values[2]
        fields_by_tag[tag] = fields

    lines = []
    current_tag = None
    written_fields = set()

    def append_missing_fields():
        if current_tag not in fields_by_tag:
            return
        for field, value in fields_by_tag[current_tag].items():
            if field not in written_fields:
                lines.append(f'{field}: {value}\n')
                written_fields.add(field)

    for line in raw_lines:
        stripped = line.rstrip()
        if stripped.startswith('Tag:'):
            append_missing_fields()
            current_tag = stripped[4:].strip()
            written_fields = set()
            lines.append(line)
            continue
        if not stripped:
            append_missing_fields()
            current_tag = None
            written_fields = set()
            lines.append(line)
            continue

        if current_tag in fields_by_tag:
            field = stripped.partition(':')[0]
            if field in fields_by_tag and (stripped.endswith(':') or ': ' in stripped):
                lines.append(f'{field}: {fields_by_tag[current_tag][field]}\n')
                written_fields.add(field)
                continue
        lines.append(line)

    append_missing_fields()
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
            issues.append(f"  NEEDS A NAME Tag {rec['Tag']}: {rec.get('Semantics', '')!r} — "
                          f"too long or unclear to shorten automatically")

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Fill Words on new db entries or review them interactively')
    parser.add_argument('--tfidf', action='store_true', help='Experimental: for CBOR tags the rules cannot name, keep the rarest words of the description')
    parser.add_argument('--llm', action='store_true', help='Use local Ollama LLM for CBOR tag text (falls back to the rules)')
    parser.add_argument('--interactive', action='store_true', help='Review each new or needs-manual record; accept, edit, skip, or quit')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be written without modifying files')
    args = parser.parse_args()

    if not os.path.isdir(db_dir):
        print(f"ERROR: db/ directory not found at {db_dir}. Run sync.py first.", file=sys.stderr)
        sys.exit(1)

    global _review_quit_requested
    _review_quit_requested = False
    all_issues = []
    for fname in sorted(os.listdir(db_dir)):
        if not fname.endswith('.rec'):
            continue
        db_file = os.path.join(db_dir, fname)
        issues = fill_words_for_file(
            db_file, use_llm=args.llm, use_tfidf=args.tfidf,
            dry_run=args.dry_run, interactive=args.interactive,
        )
        if issues:
            print(f"\n{fname}:")
            for iss in issues:
                print(iss)
            all_issues.extend(issues)
        if args.interactive and _review_quit_requested:
            break

    if all_issues:
        print(f"\n{'='*60}")
        if args.interactive:
            print(f"{len(all_issues)} entr(ies) remain for review — rerun `make review` or edit db/*.rec, then run `make check`.")
        else:
            print(f"{len(all_issues)} entr(ies) need manual Words — run `make review` "
                  f"(or edit db/*.rec and set Source: manual), then run `make check`.")
        if not args.dry_run and not (args.interactive and _review_quit_requested):
            sys.exit(1)
    elif args.interactive:
        print("Interactive review complete." + (" (dry-run)" if args.dry_run else ""))
    else:
        print("All new entries named successfully." + (" (dry-run)" if args.dry_run else ""))


if __name__ == '__main__':
    main()
