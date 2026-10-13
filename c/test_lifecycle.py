"""Tests for explicit registration lifecycle detection."""

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import check
import name
import recfile
import sync
from lifecycle import from_semantics


class LifecycleDetectionTests(unittest.TestCase):
    def test_recognizes_provisional_status_suffix(self):
        self.assertEqual(from_semantics('Item; provisional'), 'provisional')
        self.assertEqual(from_semantics('Token; PROVISIONAL'), 'provisional')

    def test_recognizes_temporary_registration_marker(self):
        semantics = 'Upload Supported (TEMPORARY - registered 2024-11-13, expires 2025-11-13)'
        self.assertEqual(from_semantics(semantics), 'temporary')

    def test_recognizes_under_review(self):
        self.assertEqual(from_semantics('Registration under review'), 'under-review')

    def test_does_not_misclassify_temporary_redirect(self):
        self.assertEqual(from_semantics('Temporary Redirect'), '')

    def test_stable_semantics_have_no_lifecycle_marker(self):
        self.assertEqual(from_semantics('permanent'), '')

    def test_lifecycle_transition_marks_record_pending_and_blocks_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'coap_content_formats.rec')
            recfile.write_header(path, 'CoapContentFormat', 'Tag', 'test')
            recfile.append_record(path, {
                'Tag': '836',
                'Words': 'application voucher as cose',
                'Semantics': 'application/voucher+cose (TEMPORARY - registered 2022-04-12)',
                'Reference': 'draft-test',
                'Source': 'heuristic',
                'Lifecycle': 'temporary',
                'Review': 'monitor',
            })

            sync._apply(
                path,
                'CoapContentFormat',
                'test',
                [('836', 'application/voucher+cose', 'draft-test')],
                dry_run=False,
            )

            record = recfile.read(path)[0]
            self.assertEqual(record['Semantics'], 'application/voucher+cose (TEMPORARY - registered 2022-04-12)')
            self.assertEqual(record['Review'], 'pending')
            self.assertEqual(record['IANA Semantics'], 'application/voucher+cose')
            self.assertTrue(any('Review=pending' in error for error in check.check_file(path)))

    def _pending_record_file(self, temp_dir):
        path = os.path.join(temp_dir, 'coap_content_formats.rec')
        recfile.write_header(path, 'CoapContentFormat', 'Tag', 'test')
        recfile.append_record(path, {
            'Tag': '836',
            'Words': 'application voucher as cose',
            'Semantics': 'application/voucher+cose (TEMPORARY - registered 2022-04-12)',
            'Reference': 'draft-test',
            'Source': 'heuristic',
            'Lifecycle': 'temporary',
            'Review': 'monitor',
        })
        sync._apply(path, 'CoapContentFormat', 'test', [('836', 'application/voucher+cose', 'draft-test')], False)
        return path

    def test_review_keeps_name_and_resolves_stable_transition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._pending_record_file(temp_dir)
            output = StringIO()
            with patch('builtins.input', side_effect=['k']), redirect_stdout(output):
                issues = name.fill_words_for_file(path, interactive=True)

            record = recfile.read(path)[0]
            self.assertEqual(issues, [])
            self.assertEqual(record['Semantics'], 'application/voucher+cose')
            self.assertNotIn('IANA Semantics', record)
            self.assertEqual((record['Lifecycle'], record['Review']), ('stable', 'resolved'))
            self.assertEqual((record['Words'], record['Source']), ('application voucher as cose', 'heuristic'))
            self.assertEqual(check.check_file(path), [])
            self.assertEqual(recfile.duplicate_fields(path), [])
            self.assertIn('temporary -> stable', output.getvalue())

    def test_review_can_rename_when_the_registration_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._pending_record_file(temp_dir)
            output = StringIO()
            with patch('builtins.input', side_effect=['1', 'e', 'Voucher COSE']), redirect_stdout(output):
                name.fill_words_for_file(path, interactive=True)

            record = recfile.read(path)[0]
            # The new text yields the current name, so there is no numbered rename to pick
            self.assertNotIn('  1) ', output.getvalue())
            self.assertEqual((record['Words'], record['Source']), ('voucher cose', 'manual'))
            self.assertEqual(record['Suggested Words'], name.NO_SUGGESTION)
            self.assertEqual(check.check_file(path), [])

    def test_review_later_leaves_record_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._pending_record_file(temp_dir)
            with patch('builtins.input', side_effect=['l']), redirect_stdout(StringIO()):
                issues = name.fill_words_for_file(path, interactive=True)

            record = recfile.read(path)[0]
            self.assertEqual(len(issues), 1)
            self.assertEqual(record['Review'], 'pending')
            self.assertEqual(record['IANA Semantics'], 'application/voucher+cose')

    def test_check_rejects_leftover_iana_semantics_and_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'cbor_tags.rec')
            with open(path, 'w', encoding='utf-8') as db:
                db.write('%rec: CborTag\n%key: Tag\n\n'
                         'Tag: 1\nWords: one\nSemantics: One\nReference:\nSource: manual\n'
                         'IANA Semantics: One changed\nWords: uno\n')
            errors = check.check_file(path)
            self.assertTrue(any("field 'Words' appears more than once" in error for error in errors))
            self.assertTrue(any('IANA Semantics is only kept while Review=pending' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
