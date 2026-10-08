"""Tests for explicit registration lifecycle detection."""

import os
import tempfile
import unittest

import check
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
            self.assertTrue(any('Review=pending' in error for error in check.check_file(path)))


if __name__ == '__main__':
    unittest.main()
