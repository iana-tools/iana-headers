#!/usr/bin/env python3
"""Experimental CBOR tag namers and side-by-side evaluation.

The TF-IDF nearest-neighbour baseline predicts name tokens by weighted voting
among similar descriptions; it is local corpus-based ML, not an LLM. An optional
--llm comparison queries an OpenAI-compatible local llama.cpp server. Neither
mode modifies the database or generated headers.

Run from the repository root:
    python3 c/experimental_namer.py --evaluate
    python3 c/experimental_namer.py --tag 18
    python3 c/experimental_namer.py --tag 107 --llm
    python3 c/experimental_namer.py --tag 107 --llm --compare-xml
    python3 c/experimental_namer.py --suggest-new --llm

The nearest-neighbour label vocabulary is limited to words already in Words.
Leave-one-out evaluation excludes each target from its own training set.
"""

import argparse
import collections
import math
import os

import name
import recfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_DB = os.path.join(REPO_DIR, 'db', 'cbor_tags.rec')
DEFAULT_PARTS = os.path.join(SCRIPT_DIR, 'experiments', 'cbor_tag_name_parts.rec')
DEFAULT_CBOR_XML = os.path.join(REPO_DIR, 'iana', 'snapshots', '2026-10-08', 'cbor', 'cbor-tags.xml')
EXCLUDED_SOURCES = {'new', 'needs-manual', 'skip'}


def _label_tokens(words):
    return list(dict.fromkeys(words.lower().split()))


def named_examples(records):
    """Return usable semantic-to-name examples, excluding intentionally skipped entries."""
    return [
        record for record in records
        if record.get('Source', '').strip() not in EXCLUDED_SOURCES
        and record.get('Semantics', '').strip()
        and record.get('Words', '').strip()
    ]


def read_name_parts(filepath):
    """Load curated experimental namespace/label annotations keyed by Tag."""
    return {row['Tag'].strip(): row for row in recfile.read(filepath) if row.get('Tag', '').strip()}


def compose_name_parts(parts):
    """Flatten explicit namespace and label fields into the usual Words token string."""
    return ' '.join(_label_tokens(' '.join((parts.get('Namespace', ''), parts.get('Label', '')))))


class SemanticNamer:
    """TF-IDF nearest-neighbour classifier with weighted multi-label voting."""

    def __init__(self, examples, neighbors=5, max_words=6):
        if neighbors < 1:
            raise ValueError('neighbors must be at least 1')
        if max_words < 1:
            raise ValueError('max_words must be at least 1')
        if not examples:
            raise ValueError('at least one named example is required')

        self.examples = list(examples)
        self.neighbors = neighbors
        self.max_words = max_words
        tokenized = [collections.Counter(name._raw_tokens(row['Semantics'])) for row in self.examples]
        document_frequency = collections.Counter()
        for tokens in tokenized:
            document_frequency.update(tokens.keys())

        count = len(self.examples)
        self.idf = {
            token: math.log((count + 1) / (frequency + 1)) + 1
            for token, frequency in document_frequency.items()
        }
        self.vectors = [self._vector(tokens) for tokens in tokenized]
        self.norms = [math.sqrt(sum(weight * weight for weight in vector.values()))
                      for vector in self.vectors]

    def _vector(self, tokens):
        return {
            token: (1 + math.log(frequency)) * self.idf[token]
            for token, frequency in tokens.items()
            if token in self.idf
        }

    def _nearest(self, semantics):
        vector = self._vector(collections.Counter(name._raw_tokens(semantics)))
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        if not norm:
            return []

        scored = []
        for example, example_vector, example_norm in zip(self.examples, self.vectors, self.norms):
            if not example_norm:
                continue
            dot = sum(weight * example_vector.get(token, 0.0)
                      for token, weight in vector.items())
            similarity = dot / (norm * example_norm)
            if similarity > 0:
                scored.append((similarity, example))
        scored.sort(key=lambda item: (-item[0], item[1].get('Tag', '')))
        return scored[:self.neighbors]

    def predict(self, semantics):
        """Return (predicted name tokens, nearest examples with cosine similarities)."""
        nearest = self._nearest(semantics)
        if not nearest:
            return [], []

        votes = collections.Counter()
        first_seen = {}
        weighted_length = 0.0
        total_similarity = 0.0
        order = 0
        for similarity, example in nearest:
            tokens = _label_tokens(example['Words'])
            if not tokens:
                continue
            total_similarity += similarity
            weighted_length += similarity * len(tokens)
            for token in tokens:
                if token not in first_seen:
                    first_seen[token] = order
                    order += 1
                votes[token] += similarity

        if not votes:
            return [], nearest

        expected_length = round(weighted_length / total_similarity)
        result_length = max(1, min(self.max_words, expected_length))
        ranked = sorted(votes, key=lambda token: (-votes[token], first_seen[token]))
        return ranked[:result_length], nearest


def _metrics(examples, predictions):
    exact = 0
    matched = 0
    predicted_count = 0
    expected_count = 0
    for example in examples:
        expected = set(_label_tokens(example['Words']))
        predicted = set(predictions.get(example['Tag'], []))
        exact += predicted == expected
        matched += len(predicted & expected)
        predicted_count += len(predicted)
        expected_count += len(expected)
    precision = matched / predicted_count if predicted_count else 0.0
    recall = matched / expected_count if expected_count else 0.0
    return exact / len(examples), precision, recall


def evaluate(examples, neighbors=5, max_words=6):
    """Leave one record out at a time and compare the model with the rule namer."""
    model_predictions = {}
    heuristic_predictions = {}
    nearest_by_tag = {}

    for held_out in examples:
        training = [row for row in examples if row is not held_out]
        if not training:
            continue
        model = SemanticNamer(training, neighbors=neighbors, max_words=max_words)
        predicted, nearest = model.predict(held_out['Semantics'])
        model_predictions[held_out['Tag']] = predicted
        nearest_by_tag[held_out['Tag']] = nearest
        heuristic_predictions[held_out['Tag']] = _label_tokens(
            name.cbor_tag_words(held_out)
        )

    model_exact, model_precision, model_recall = _metrics(examples, model_predictions)
    rule_exact, rule_precision, rule_recall = _metrics(examples, heuristic_predictions)
    return {
        'count': len(examples),
        'model': (model_exact, model_precision, model_recall),
        'heuristic': (rule_exact, rule_precision, rule_recall),
        'predictions': model_predictions,
        'nearest': nearest_by_tag,
    }


def _print_metrics(label, examples, result):
    exact, precision, recall = result
    print(f'{label}: {len(examples)} records')
    print(f'  exact name: {exact:.1%}')
    print(f'  token precision/recall: {precision:.1%} / {recall:.1%}')


def print_evaluation(examples, outcome):
    print('Leave-one-out evaluation (each record is excluded from its own training set)')
    print(f"Examples: {outcome['count']} named CBOR tags")
    _print_metrics('TF-IDF k-NN', examples, outcome['model'])
    _print_metrics('Current heuristic', examples, outcome['heuristic'])

    for source in ('heuristic', 'manual'):
        subset = [row for row in examples if row.get('Source', '').strip() == source]
        if subset:
            print(f'\nSource: {source}')
            _print_metrics('TF-IDF k-NN', subset,
                           _metrics(subset, outcome['predictions']))
            _print_metrics('Current heuristic', subset,
                           _metrics(subset, {
                               row['Tag']: _label_tokens(name.cbor_tag_words(row))
                               for row in subset
                           }))


def select_prompt_examples(record, examples, nearest, name_parts, limit=10):
    """Prefer examples from the same curated namespace, then nearest semantic matches."""
    target_tag = record.get('Tag', '').strip()
    target_namespace = (name_parts.get(target_tag, {}).get('Namespace', '').strip().casefold())
    similarity_by_tag = {row.get('Tag', '').strip(): score for score, row in nearest}
    selected = []
    seen_tags = {target_tag}

    if target_namespace:
        same_namespace = [
            row for row in examples
            if row.get('Tag', '').strip() != target_tag
            and name_parts.get(row.get('Tag', '').strip(), {}).get('Namespace', '').strip().casefold()
            == target_namespace
        ]
        same_namespace.sort(key=lambda row: (
            -similarity_by_tag.get(row.get('Tag', '').strip(), 0.0),
            row.get('Tag', '').strip(),
        ))
        for row in same_namespace:
            tag = row.get('Tag', '').strip()
            if tag not in seen_tags and len(selected) < limit:
                selected.append(row)
                seen_tags.add(tag)

    for _, row in nearest:
        tag = row.get('Tag', '').strip()
        if tag not in seen_tags and len(selected) < limit:
            selected.append(row)
            seen_tags.add(tag)

    if not selected:
        return [row for row in examples if row.get('Tag', '').strip() != target_tag][:limit]
    return selected


def format_xml_name_fields(xml_record):
    """Present selected IANA XML fields separately, keeping citations distinct from semantics."""
    return '\n'.join((
        f"Tag: {xml_record.get('value', '')}",
        f"Data item/description: {xml_record.get('description', '')}",
        f"Semantics: {xml_record.get('semantics', '')}",
        f"Reference (citation only): {xml_record.get('xref', '')}",
    ))


def read_cbor_xml_records(xml_path):
    """Read the CBOR tag records from an archived IANA XML source."""
    import iana_header_utils as utils

    with open(xml_path, 'r', encoding='utf-8') as source:
        return utils.parse_iana_xml_registry(source.read(), 'tags')


def query_local_llm(semantics, examples, endpoint, model_name, temperature, structured_fields=None):
    """Ask an OpenAI-compatible local llama.cpp server for a naming suggestion."""
    import json
    import urllib.error
    import urllib.request

    examples_text = '\n'.join(
        f'  Semantics: "{row["Semantics"]}" -> Words: "{row["Words"]}"'
        for row in examples[:10]
    )
    if structured_fields is None:
        target_text = f'Semantics: "{semantics}"'
        field_guidance = ''
    else:
        target_text = format_xml_name_fields(structured_fields)
        field_guidance = (
            'The data item/description gives the CBOR data type, while Semantics gives its meaning. '
            'Reference is citation metadata and must not become name tokens.\n'
        )
    prompt = (
        'You generate short lowercase word tokens for IANA CBOR tag entries. '
        'Tokens are space-separated, no punctuation, 1-6 words max.\n'
        f'{field_guidance}'
        f'Examples:\n{examples_text}\n'
        f'Now produce Words for this entry:\n{target_text}\n'
        'Respond with only the token string, nothing else.'
    )
    payload = json.dumps({
        'model': model_name,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': 256,
        'chat_template_kwargs': {'enable_thinking': False},
    }).encode('utf-8')
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read())
        return result['choices'][0]['message']['content'].strip()
    except (OSError, ValueError, KeyError, IndexError, urllib.error.HTTPError) as exc:
        return f'(LLM request failed: {exc})'


def print_suggestion(record, model, show_expected=False, llm_config=None, examples=None,
                     name_parts=None, xml_record=None, compare_xml=False):
    semantics = record.get('Semantics', '')
    words, nearest = model.predict(semantics)
    source = record.get('Source', '').strip()
    print(f"Tag {record.get('Tag', '?')} [{source}]")
    print(f'  Full IANA Semantics: {semantics}')
    print(f"  Current heuristic: {name.cbor_tag_words(record) or '(no suggestion)'}")
    print(f"  TF-IDF k-NN suggestion: {' '.join(words) if words else '(no suggestion)'}")
    if xml_record:
        print('  IANA XML fields:')
        for line in format_xml_name_fields(xml_record).splitlines():
            print(f'    {line}')
        xml_semantics = xml_record.get('semantics', '')
        print(f"  Heuristic (XML Semantics): {name.cbor_tag_words({'Tag': xml_record.get('value', ''), 'Semantics': xml_semantics}) or '(no suggestion)'}")
    parts = (name_parts or {}).get(record.get('Tag', '').strip())
    if parts:
        print(f"  Curated parts: Namespace={parts.get('Namespace', '')}; Label={parts.get('Label', '')}")
        print(f'  Structured composition: {compose_name_parts(parts)}')
    if llm_config:
        prompt_examples = select_prompt_examples(record, examples or [], nearest, name_parts or {})
        print('  LLM context tags: ' + ', '.join(row.get('Tag', '') for row in prompt_examples))
        if compare_xml and xml_record:
            xml_semantics = xml_record.get('semantics', '')
            text_suggestion = query_local_llm(xml_semantics, prompt_examples, *llm_config)
            print(f'  LLM (XML Semantics only): {text_suggestion}')
            structured_suggestion = query_local_llm(
                xml_semantics, prompt_examples, *llm_config, structured_fields=xml_record
            )
            print(f'  LLM (separate XML fields): {structured_suggestion}')
        else:
            suggestion = query_local_llm(semantics, prompt_examples, *llm_config)
            print(f'  Local LLM suggestion: {suggestion}')
    if show_expected and record.get('Words', '').strip():
        print(f"  Stored Words: {record['Words']}")
    if nearest:
        print('  Nearest examples:')
        for similarity, example in nearest:
            print(f"    {similarity:.3f}  Tag {example.get('Tag')}: {example['Words']} — {example['Semantics']}")
    else:
        print('  Nearest examples: none (no overlapping description terms)')


def main():
    parser = argparse.ArgumentParser(description='Experiment with local ML naming suggestions for CBOR tags')
    parser.add_argument('--db', default=DEFAULT_DB, help='CBOR tag recfile (default: db/cbor_tags.rec)')
    parser.add_argument('--parts', default=DEFAULT_PARTS,
                        help='curated namespace/label sidecar (default: c/experiments/cbor_tag_name_parts.rec)')
    parser.add_argument('--neighbors', type=int, default=5, help='number of similar records to vote over (default: 5)')
    parser.add_argument('--max-words', type=int, default=6, help='maximum suggested name tokens (default: 6)')
    parser.add_argument('--evaluate', action='store_true', help='run leave-one-out comparison against current names and heuristic')
    parser.add_argument('--suggest-new', action='store_true', help='suggest names for Source:new records; does not write changes')
    parser.add_argument('--tag', help='show a leave-one-out suggestion for this existing tag')
    parser.add_argument('--llm', action='store_true', help='also query a local OpenAI-compatible llama.cpp server')
    parser.add_argument('--compare-xml', action='store_true',
                        help='compare LLM input as XML Semantics text versus separate XML fields (requires --llm and --tag)')
    parser.add_argument('--xml-file', default=DEFAULT_CBOR_XML,
                        help='archived CBOR tags XML for --compare-xml')
    parser.add_argument('--llm-url', default='http://127.0.0.1:8080/v1/chat/completions',
                        help='local chat completions endpoint')
    parser.add_argument('--llm-model', default='empero-ai/Qwen3.8-27B-Ridge-GGUF:7BPW',
                        help='model id advertised by the local server')
    parser.add_argument('--temperature', type=float, default=0.0,
                        help='LLM sampling temperature (default: 0; raise it to explore varied suggestions)')
    args = parser.parse_args()
    llm_config = (args.llm_url, args.llm_model, args.temperature) if args.llm else None
    if args.compare_xml and (not args.llm or args.tag is None):
        parser.error('--compare-xml requires both --llm and --tag')

    xml_records = read_cbor_xml_records(args.xml_file) if args.compare_xml else []
    records = recfile.read(args.db)
    if not records:
        parser.error(f'no records found in {args.db}')

    name_parts = read_name_parts(args.parts)
    examples = named_examples(records)
    if not examples:
        parser.error(f'no named records with semantics found in {args.db}')

    if args.tag is not None:
        target = next((row for row in examples if row.get('Tag', '').strip() == args.tag), None)
        if target is None:
            parser.error(f'tag {args.tag!r} is not a named CBOR record in {args.db}')
        training = [row for row in examples if row is not target]
        if not training:
            parser.error('need at least two named records to suggest a held-out tag')
        model = SemanticNamer(training, neighbors=args.neighbors, max_words=args.max_words)
        xml_record = next((row for row in xml_records if row.get('value', '').strip() == args.tag), None)
        if args.compare_xml and xml_record is None:
            parser.error(f'tag {args.tag!r} is not present in XML source {args.xml_file}')
        print_suggestion(target, model, show_expected=True, llm_config=llm_config,
                         examples=training, name_parts=name_parts, xml_record=xml_record,
                         compare_xml=args.compare_xml)
        return

    if args.suggest_new:
        new_records = [row for row in records if row.get('Source', '').strip() == 'new']
        if not new_records:
            print('No Source:new CBOR records to suggest names for.')
            return
        model = SemanticNamer(examples, neighbors=args.neighbors, max_words=args.max_words)
        for record in new_records:
            print_suggestion(record, model, llm_config=llm_config, examples=examples,
                             name_parts=name_parts)
        return

    outcome = evaluate(examples, neighbors=args.neighbors, max_words=args.max_words)
    print_evaluation(examples, outcome)


if __name__ == '__main__':
    main()
