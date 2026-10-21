#!/usr/bin/env python3
"""
cbor_names_v2.py — proposed v2 CBOR tag names, derived only from the IANA registry fields.

Rules (see DEVELOPMENT.md, "CBOR tag names v2"):
1. A `ur:<type>` registration is named by its UR type.
2. A spelled-out phrase followed by its acronym in parentheses becomes the acronym
   ("CBOR Web Token (CWT)" -> "cwt").
3. Otherwise a short noun phrase from Semantics: citations, parentheticals, sentence frames
   ("A CBOR tag that contains", "The tagged CBOR array contains", "indicates that") and trailing
   clauses (after ';', ':', ', ', '. ', ' that ', ' which ', ...) are dropped; so are a/an/the.
4. If that is still a sentence (verbs such as "contains", or more than PREFERRED_WORDS words), a
   unique, meaningful last path segment of a reference URL is used instead ("…/indirection").
5. Full words, except a fixed short list of universal abbreviations (id, config, info, ref).
6. A parenthetical qualifier is put back only where dropping it makes two names collide
   ("expected base16" vs "expected base16 lowercase").

Nothing here reads anything but db/cbor_tags.rec. Spec names that IANA does not state (COSE_Sign1
for tag 18) are out of reach by design; that is step 2 (looking them up in the referenced RFCs).
"""

import argparse
import collections
import os
import re
import sys

import name
import recfile

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
CBOR_TAGS = os.path.join(repo_dir, 'db', 'cbor_tags.rec')

PREFERRED_WORDS = 5
ABBREVIATIONS = {'identifier': 'id', 'identifiers': 'ids', 'configuration': 'config',
                 'information': 'info', 'reference': 'ref', 'references': 'refs'}
ARTICLES = {'a', 'an', 'the'}
# A name containing one of these reads as a sentence, not as the name of a thing
SENTENCE_WORDS = {'contains', 'containing', 'indicates', 'is', 'are', 'can', 'be', 'use', 'used', 'define',
                  'defines', 'identify', 'given', 'stored', 'instead', 'itself'}
SENTENCE_FRAMES = [
    r'^A CBOR tag that contains(?: either| an| a)?\b\s*:?\s*',
    r'^(?:The\s+)?tagged CBOR (?:array|map|item) (?:containing|that contains|contains)(?: an?\b)?\s*',
    r'^.*?\bindicates that the payload is(?: an?\b)?\s*',
    r'^(?:hint that )?indicates that (?:the )?',
    r'^hint that indicates (?:an? )?',
    r'^identify and define (?:an? )?',
    r'^CBOR[- ]encoded\s+(?=\w+\s+\w)',
]
# Where a describing clause starts; the name is the text before the first one
CLAUSE_START = r'\s*(?:;|:(?!\w|//)|\.\s|\.$|,(?=\s)|\s(?:that|which|whose|where|as defined in|as described in|see)\b)'
# Reference URL path words that say nothing about one tag
SLUG_NOISE = {'cbor', 'tag', 'tags', 'spec', 'readme', 'index', 'extended', 'master', 'main'}


def _words(text):
    text = re.sub(r'\s\+\s', ' plus ', text)  # 'uint + 128'
    return [w for w in re.sub(r'[^a-z0-9]+', ' ', text.lower()).split()]


def _finish(words):
    words = [ABBREVIATIONS.get(w, w) for w in words if w not in ARTICLES]
    return ' '.join(words)


def _acronym_matches(acronym, words):
    letters = [c for c in acronym if c.isupper() or c.isdigit()]
    return len(letters) == len(words) and all(w[:1].upper() == c for w, c in zip(words, letters))


def _apply_acronyms(text):
    """'DDoS Open Threat Signaling (DOTS) signal channel' -> 'DOTS signal channel'."""
    def replace(match):
        before, inner = match.group(1), match.group(2).split()
        acronym, tail = inner[0], inner[1:]
        words = before.split()
        if tail and [w.lower() for w in words[-len(tail):]] == [t.lower() for t in tail]:
            words = words[:-len(tail)]  # 'Identifier reference (IRI reference)'
        letters = sum(c.isupper() or c.isdigit() for c in acronym)
        if letters < 2 or not _acronym_matches(acronym, words[-letters:]):
            return match.group(0)
        return ' '.join(words[:-letters] + [acronym] + list(tail))
    replaced = re.sub(r'((?:^|\S.*?)\S)\s*\(([A-Za-z][A-Za-z0-9]{1,7}(?: [a-z]+)*)\)', replace, text, count=1)
    return replaced, replaced != text


def _strip_frames(s):
    for _ in range(2):  # a frame can follow an article: 'A CBOR encoded Openswan file'
        for frame in SENTENCE_FRAMES:
            s = re.sub(frame, '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?i)^(?:a|an|the)\s+(?=\S)', '', s)
    return s


def _cut_clause(s, keep_commas):
    """Cut at the first describing clause; return (head, tail). A comma followed by a short attribute
    ('uint16, big endian, Typed Array', 'Multi-dimensional Array, row-major order') is part of the name."""
    for match in re.finditer(CLAUSE_START, s, flags=re.IGNORECASE):
        head = s[:match.start()].strip()
        if match.group().strip() == ',':
            following = s[match.end():].split(',', 1)[0]
            if keep_commas or len(head.split()) < 2 or len(following.split()) <= 3:
                continue
        if not head:
            continue
        return head.rstrip(',').strip(), s[match.end():].strip()
    return s.strip(), ''


def _clean_semantics(semantics):
    """Return (noun phrase, words to put back on a collision, acronym used)."""
    s = ' '.join(semantics.split())
    unwrapped = s.startswith('[') and s.endswith(']')
    if unwrapped:
        s = s[1:-1]  # '[COSE algorithm identifier, Base Hash value]' is the whole description
    s = re.sub(r'\[[^\]]*\]', '', s)  # citations
    s, used_acronym = _apply_acronyms(s)
    qualifiers = [q for q in re.findall(r'\(([^()]*)\)', s) if q.strip()]
    s = re.sub(r'\s*\([^()]*\)', '', s)
    s = _strip_frames(s)
    s = re.sub(r'(?i)^expected conversion to (\S+) encoding\b', r'expected \1', s)
    s, tail = _cut_clause(s, keep_commas=unwrapped)
    # Pointers into the spec ('see Section 3.4.5.2', 'RFC 9562') never become part of a name
    def detail(text):
        return [] if re.search(r'(?i)\b(?:see|section|rfc)\b|\d{4}', text) else _words(text)
    reserve = [detail(tail)] if tail and len(tail.split()) <= 6 else []
    reserve += [detail(q) for q in qualifiers]
    return s, [r for r in reserve if r], used_acronym


def _reference_slugs(reference):
    """Meaningful last path segments of the reference URLs: '.../cbor-tag-text-key-map' -> 'text key map'."""
    slugs = []
    for url in re.findall(r'\[(https?://[^\]\s]+)\]', reference):
        segment = re.sub(r'\.(md|html?|txt|rst)$', '', url.rstrip('/').rsplit('/', 1)[-1], flags=re.IGNORECASE)
        words = [w for w in _words(segment) if w not in SLUG_NOISE and not re.fullmatch(r'tag\d+|\d+', w)]
        if words and re.search('[a-z]{3}', ' '.join(words)):
            slugs.append(' '.join(words))
    return slugs


def _sentence_like(words):
    return len(words) > PREFERRED_WORDS or bool(SENTENCE_WORDS & set(words))


def propose(rec, slug_counts):
    """Return (words, source, list of word lists that can be appended to resolve a collision)."""
    semantics = rec.get('Semantics', '')
    ur = re.match(r'\s*ur:([a-z0-9-]+),?\s*(.*)$', semantics)
    if ur:
        description, _ = _cut_clause(re.sub(r'\s*\([^()]*\)|\[[^\]]*\]', '', ur.group(2)), keep_commas=False)
        return _finish(['ur'] + _words(ur.group(1))), 'ur type', [_words(description)]

    text, reserve, used_acronym = _clean_semantics(semantics)
    words = _finish(_words(text)).split()
    source = 'IANA acronym' if used_acronym else 'IANA text'
    if not words or _sentence_like(words):
        unique = [s for s in _reference_slugs(rec.get('Reference', '')) if slug_counts[s] == 1]
        if unique:
            return _finish(unique[0].split()), 'reference URL', []
        item = name.data_item_name(rec.get('Data Item', ''))  # 'Proof of Process Packet (PPPP)'
        if item:
            return _finish(_words(item)), 'Data Item', []
    return ' '.join(words), source, reserve


def propose_all(records):
    """{tag: (v2 words, source)} for every named CBOR tag record, and the collisions that remain."""
    named = [r for r in records if r.get('Tag', '').strip() and r.get('Source', '').strip() != 'skip']
    slug_counts = collections.Counter(s for r in named for s in set(_reference_slugs(r.get('Reference', ''))))
    proposals = {r['Tag'].strip(): list(propose(r, slug_counts)) for r in named}

    def collisions():
        seen = collections.defaultdict(list)
        for tag, (words, _, _) in proposals.items():
            if words:
                seen[words].append(tag)
        return {words: tags for words, tags in seen.items() if len(tags) > 1}

    # Put dropped detail back, one piece at a time, until names are unique:
    # 'multi dimensional array' -> '... row major order'; 'object id' -> '... ber encoding'
    for _ in range(3):
        clashes = collisions()
        if not clashes:
            break
        for tags in clashes.values():
            for tag in tags:
                words, source, reserve = proposals[tag]
                if reserve:
                    proposals[tag] = [_finish(words.split() + reserve[0]), source + ' + detail', reserve[1:]]

    # A human decision (Source: manual) stands where the rules give no unique name
    by_tag = {r['Tag'].strip(): r for r in named}
    clashes = collisions()
    for tag, (words, source, _) in proposals.items():
        manual = by_tag[tag].get('Source', '').strip() == 'manual'
        if manual and (not words or any(tag in tags for tags in clashes.values())):
            proposals[tag] = [by_tag[tag]['Words'].strip(), 'manual (v1)', []]
    return {tag: (words, source) for tag, (words, source, _) in proposals.items()}, collisions()


def preview(records, proposals, collisions):
    by_tag = {r['Tag'].strip(): r for r in records}
    rows, changed = [], 0
    sources = collections.Counter()
    long_names = 0
    spelling_only = 0
    expansions = {short: full for full, short in {**name._VERY_COMMON_ABBREV, **name._LONG_ABBREV}.items()}
    colliding = {tag for tags in collisions.values() for tag in tags}
    for tag, (v2, source) in proposals.items():
        rec = by_tag[tag]
        v1 = rec.get('Words', '').strip()
        sources[source] += 1
        flags = []
        if v2 != v1:
            changed += 1
            if v1 and [expansions.get(w, w) for w in v1.split()] == [expansions.get(w, w) for w in v2.split()]:
                spelling_only += 1
                flags.append('spelling only')
        if not v2:
            flags.append('no name')
        elif len(v2.split()) > PREFERRED_WORDS:
            long_names += 1
            flags.append(f'{len(v2.split())} words')
        if tag in colliding:
            flags.append('collides')
        if v1 and v2 != v1:
            rows.append((tag, v1, v2, source, ', '.join(flags), rec.get('Semantics', '')))
        elif not v1:
            rows.append((tag, '(unnamed)', v2, source, ', '.join(flags), rec.get('Semantics', '')))

    def ident(words):
        return f"`{'_'.join(words.split()).upper()}`" if words and not words.startswith('(') else words

    def cell(text, limit=90):
        text = ' '.join(text.split()).replace('|', '\\|')
        return text if len(text) <= limit else text[:limit - 1] + '…'

    out = [
        '# CBOR tag names v2 — IANA-only rules (step 1)', '',
        f'{len(proposals)} tags · **{changed} change** ({spelling_only} only spell out an abbreviation), '
        f'{len(proposals) - changed} keep their v1 name · {long_names} still longer than {PREFERRED_WORDS} words · '
        f'{len(colliding)} still colliding', '',
        'Sources: ' + ', '.join(f'{source} {count}' for source, count in sources.most_common()), '',
        'Names are shown without the `CBOR_TAG_` prefix. Only tags whose name changes are listed.', '',
        '| Tag | v1 | v2 | From | Flags | IANA Semantics |', '| --- | --- | --- | --- | --- | --- |',
    ]
    for tag, v1, v2, source, flags, semantics in rows:
        out.append(f'| {tag} | {ident(v1)} | {ident(v2)} | {source} | {flags} | {cell(semantics)} |')

    unchanged_long = [(tag, v2) for tag, (v2, _) in proposals.items()
                      if len(v2.split()) > PREFERRED_WORDS and v2 == by_tag[tag].get('Words', '').strip()]
    if unchanged_long:
        out += ['', f'## Unchanged but longer than {PREFERRED_WORDS} words', '',
                'Most are systematic (typed arrays) and fine; the rest need a spec name or a human.', '',
                '| Tag | Name | IANA Semantics |', '| --- | --- | --- |']
        out += [f'| {tag} | {ident(v2)} | {cell(by_tag[tag].get("Semantics", ""))} |' for tag, v2 in unchanged_long]
    return '\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description='Preview v2 CBOR tag names derived from the IANA fields only')
    parser.add_argument('--output', help='write the Markdown preview here instead of stdout')
    args = parser.parse_args()
    records = recfile.read(CBOR_TAGS)
    proposals, collisions = propose_all(records)
    markdown = preview(records, proposals, collisions)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(markdown)
    else:
        sys.stdout.write(markdown)


if __name__ == '__main__':
    main()
