"""Regression tests for CBOR semantic name generation."""

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import name
import recfile


class CborNameTests(unittest.TestCase):
    def test_historical_semantic_overrides_are_replaced_by_general_rules(self):
        cases = [
            ('107', 'SUIT_Envelope as defined in Appendix A of [RFC-ietf-suit-manifest-33]', 'suit envelope'),
            ('1070', 'SUIT_Manifest as defined in Appendix A of [RFC-ietf-suit-manifest-33]', 'suit manifest'),
            ('108', 'Expected conversion to base16 encoding (lowercase)',
             'expected conversion base16 enc lowercase'),
            ('527', 'A CBOR tag that contains either: xcorimmap, or signed-xcorim.',
             'xcorimmap or signed xcorim'),
            ('32870', 'Logical operator: NONE / NOT. Encodes the logical operation (!item).',
             'logical operator none or not'),
            ('32871', 'Logical operator: ANY. Encodes the logical operation (item1||item2).',
             'logical operator any'),
            ('32872', 'Logical operator: ALL. Encodes the logical operation (item1&&item2).',
             'logical operator all'),
            ('41728', 'Fraction', 'fraction'),
            ('41729', 'Fraction (-NaN signals)', 'fraction negative nan signals'),
            ('41730', 'Fraction (+NaN signals)', 'fraction positive nan signals'),
            ('41731', 'Fraction (Both NaNs signal)', 'fraction both nan signals'),
        ]
        for tag, semantics, expected in cases:
            with self.subTest(tag=tag):
                self.assertEqual(name.cbor_tag_words({'Tag': tag, 'Semantics': semantics}), expected)

    def test_invalid_sentinel_names_use_exact_tag_values(self):
        cases = {
            '65535': 'invalid 16bit',
            '4294967295': 'invalid 32bit',
            '18446744073709551615': 'invalid 64bit',
        }
        for tag, expected in cases.items():
            with self.subTest(tag=tag):
                self.assertEqual(
                    name.cbor_tag_words({'Tag': tag, 'Semantics': 'always invalid; see Section 10.1'}),
                    expected,
                )

        self.assertEqual(
            name.cbor_tag_words({'Tag': '165535', 'Semantics': 'always invalid; see Section 10.1'}),
            'always invalid',
        )

    def test_duplicate_historical_entries_remain_skipped(self):
        semantics = 'A CBOR tag that contains a PEM encoded SubjectPublicKeyInfo.'
        for tag in ('554', '555'):
            with self.subTest(tag=tag):
                self.assertEqual(name.cbor_tag_words({'Tag': tag, 'Semantics': semantics}), '')

    def test_fully_bracketed_semantics_keep_their_contents(self):
        self.assertEqual(
            name.cbor_text_words('[COSE algorithm identifier, Base Hash value]'),
            'cose algorithm id base hash value',
        )

    def test_interactive_review_accepts_and_edits_colliding_suggestions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            with open(db_file, 'w', encoding='utf-8') as db:
                db.write(
                    '%rec: CborTag\n%key: Tag\n\n'
                    'Tag: 1\nWords:\nData Item: unsigned integer\n'
                    'Semantics: Compact unsigned integer representation\n'
                    'Reference: [RFC]\nSource: new\n\n'
                    'Tag: 2\nWords:\nSemantics: Compact unsigned integer representation\n'
                    'Reference: [RFC]\nSource: new\n'
                )

            output = StringIO()
            with patch('builtins.input', side_effect=['a', 'e', 'alternate integer']), redirect_stdout(output):
                issues = name.fill_words_for_file(db_file, interactive=True)

            records = recfile.read(db_file)
            self.assertEqual(issues, [])
            self.assertEqual(records[0]['Source'], 'manual')
            self.assertEqual(records[1]['Source'], 'manual')
            self.assertEqual(records[1]['Words'], 'alternate integer')
            self.assertIn('IANA Data Item: unsigned integer', output.getvalue())

    def test_interactive_quit_leaves_pending_records_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            with open(db_file, 'w', encoding='utf-8') as db:
                db.write(
                    '%rec: CborTag\n%key: Tag\n\n'
                    'Tag: 4\nWords:\nSemantics: First suggestion\nReference:\nSource: new\n\n'
                    'Tag: 5\nWords:\nSemantics: Second suggestion\nReference:\nSource: new\n'
                )

            with patch('builtins.input', side_effect=['q']), redirect_stdout(StringIO()):
                issues = name.fill_words_for_file(db_file, interactive=True)

            records = recfile.read(db_file)
            self.assertEqual(len(issues), 2)
            self.assertTrue(name._review_quit_requested)
            self.assertEqual([record['Source'] for record in records], ['new', 'new'])
            name._review_quit_requested = False

    def test_interactive_skip_persists_its_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            with open(db_file, 'w', encoding='utf-8') as db:
                db.write(
                    '%rec: CborTag\n%key: Tag\n\n'
                    'Tag: 3\nWords:\nSemantics: Ambiguous duplicate registration\n'
                    'Reference: [IANA]\nSource: new\n'
                )

            with patch('builtins.input', side_effect=['s', 'duplicate semantics; omit pending clarification']), redirect_stdout(StringIO()):
                issues = name.fill_words_for_file(db_file, interactive=True)

            record = recfile.read(db_file)[0]
            self.assertEqual(issues, [])
            self.assertEqual(record['Source'], 'skip')
            self.assertEqual(record['Note'], 'duplicate semantics; omit pending clarification')


if __name__ == '__main__':
    unittest.main()
