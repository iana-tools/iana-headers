"""Tests for the standalone experimental semantic namer."""

import unittest

import recfile
from experimental_namer import (
    DEFAULT_DB,
    DEFAULT_PARTS,
    SemanticNamer,
    compose_name_parts,
    read_name_parts,
    select_prompt_examples,
)


class SemanticNamerTests(unittest.TestCase):
    def setUp(self):
        self.examples = [
            {
                'Tag': '1',
                'Semantics': 'Compact unsigned integer representation',
                'Words': 'unsigned integer',
                'Source': 'heuristic',
            },
            {
                'Tag': '2',
                'Semantics': 'Compact signed integer representation',
                'Words': 'signed integer',
                'Source': 'heuristic',
            },
        ]

    def test_nearest_description_votes_for_its_name_tokens(self):
        model = SemanticNamer(self.examples, neighbors=1)

        words, nearest = model.predict('Compact unsigned integer encoding')

        self.assertEqual(words, ['unsigned', 'integer'])
        self.assertEqual(nearest[0][1]['Tag'], '1')

    def test_unrelated_text_has_no_prediction(self):
        model = SemanticNamer(self.examples)

        words, nearest = model.predict('completely unrelated vocabulary')

        self.assertEqual(words, [])
        self.assertEqual(nearest, [])

    def test_rejects_empty_training_set(self):
        with self.assertRaises(ValueError):
            SemanticNamer([])

    def test_namespace_and_label_compose_into_name_words(self):
        words = compose_name_parts({'Namespace': 'SUIT', 'Label': 'Envelope'})

        self.assertEqual(words, 'suit envelope')

    def test_curated_parts_reproduce_stored_words(self):
        records = {row['Tag'].strip(): row for row in recfile.read(DEFAULT_DB)}
        parts_by_tag = read_name_parts(DEFAULT_PARTS)

        for tag, parts in parts_by_tag.items():
            with self.subTest(tag=tag):
                self.assertEqual(compose_name_parts(parts), records[tag]['Words'])

    def test_prompt_examples_prefer_same_namespace(self):
        cose = {'Tag': '16', 'Semantics': 'COSE encrypted object', 'Words': 'cose encrypted object'}
        suit = {'Tag': '1070', 'Semantics': 'SUIT manifest', 'Words': 'suit manifest'}
        target = {'Tag': '107', 'Semantics': 'SUIT envelope'}
        parts = {
            '16': {'Namespace': 'COSE'},
            '107': {'Namespace': 'SUIT'},
            '1070': {'Namespace': 'SUIT'},
        }

        selected = select_prompt_examples(target, [cose, suit], [(0.9, cose), (0.8, suit)], parts)

        self.assertEqual([row['Tag'] for row in selected], ['1070', '16'])


if __name__ == '__main__':
    unittest.main()
