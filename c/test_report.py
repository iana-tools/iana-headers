"""Tests for the pull request summary of db/ changes."""

import os
import tempfile
import unittest

import recfile
import report


BASE = '''%rec: CborTag
%key: Tag

Tag: 1
Words: epoch based date time
Semantics: Epoch-based date/time
Reference: [RFC8949]
Source: heuristic

Tag: 2
Words: unsigned bignum
Semantics: Unsigned bignum
Reference: [RFC8949]
Source: heuristic

Tag: 3
Words: negative bignum
Semantics: Negative bignum
Reference: [RFC8949]
Source: heuristic

Tag: 60
Words: redacted claim
Semantics: Redacted claim (TEMPORARY - registered 2025-12-09)
Reference: [draft]
Source: manual
Lifecycle: temporary
Review: monitor
'''


class ReportTests(unittest.TestCase):
    def _compare(self, head_text, base_text=BASE):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            with open(db_file, 'w', encoding='utf-8') as db:
                db.write(head_text)
            sections, breaking = report.compare(lambda fname: recfile.parse(base_text), [db_file])
        return sections, breaking, report.render('`main`', sections, breaking)

    def test_unchanged_db_reports_nothing(self):
        sections, breaking, markdown = self._compare(BASE)
        self.assertEqual(breaking, [])
        self.assertIn('No changes', markdown)

    def test_new_records_and_open_decisions_are_listed(self):
        head = BASE + '''
Tag: 501
Words: corim map
Semantics: A CBOR tag that contains a corim-map.
Reference: [TCG]
Source: manual
Suggested Words: corim map
Suggested By: heuristic

Tag: 502
Words: corim
Semantics: A CBOR tag that contains a corim.
Reference: [TCG]
Source: manual
Suggested Words: corim document
Suggested By: heuristic

Tag: 58
Words:
Semantics: An array claim element intended to be redacted, or a map key whose key and value are redacted.
Reference: [draft]
Source: needs-manual
Suggested Words: (none)
Suggested By: heuristic

Tag: 9
Words:
Semantics: Withdrawn | duplicate
Reference: [draft]
Source: skip
Note: duplicate of tag 2
'''
        sections, breaking, markdown = self._compare(head)
        self.assertEqual(breaking, [])
        self.assertIn('`CBOR_TAG_CORIM_MAP` | heuristic suggestion accepted', markdown)
        self.assertIn('`CBOR_TAG_CORIM` | edited (suggested: corim document)', markdown)
        self.assertIn('| cbor_tags.rec | 58 | no usable suggestion |', markdown)
        self.assertIn('| cbor_tags.rec | 9 | duplicate of tag 2 | Withdrawn \\| duplicate |', markdown)
        self.assertIn('**1 need a decision**', markdown)

    def test_renaming_a_published_name_is_breaking_unless_documented(self):
        renamed = BASE.replace('Words: unsigned bignum', 'Words: positive bignum')
        _, breaking, markdown = self._compare(renamed)
        self.assertEqual(breaking, ['cbor_tags.rec Tag 2'])
        self.assertIn('`CBOR_TAG_UNSIGNED_BIGNUM` | `CBOR_TAG_POSITIVE_BIGNUM`', markdown)

        documented = renamed.replace('Words: positive bignum', 'Words: positive bignum\nPrevious Words: unsigned bignum')
        sections, breaking, _ = self._compare(documented)
        self.assertEqual(breaking, [])
        self.assertEqual(len(sections['renamed']), 1)

    def test_temporary_registration_may_be_renamed(self):
        _, breaking, markdown = self._compare(BASE.replace('Words: redacted claim', 'Words: redacted claim key'))
        self.assertEqual(breaking, [])
        self.assertIn('Expected renames', markdown)

    def test_deleting_or_skipping_a_published_record_is_breaking(self):
        deleted = BASE.replace('''Tag: 3
Words: negative bignum
Semantics: Negative bignum
Reference: [RFC8949]
Source: heuristic

''', '')
        _, breaking, _ = self._compare(deleted)
        self.assertEqual(breaking, ['cbor_tags.rec Tag 3'])

        skipped = BASE.replace('Words: negative bignum\nSemantics: Negative bignum\nReference: [RFC8949]\nSource: heuristic',
                               'Words:\nSemantics: Negative bignum\nReference: [RFC8949]\nSource: skip')
        _, breaking, _ = self._compare(skipped)
        self.assertEqual(breaking, ['cbor_tags.rec Tag 3'])

    def test_lifecycle_changes_are_listed(self):
        resolved = BASE.replace('Semantics: Redacted claim (TEMPORARY - registered 2025-12-09)\nReference: [draft]\n'
                                'Source: manual\nLifecycle: temporary\nReview: monitor',
                                'Semantics: Redacted claim\nReference: [RFC]\nSource: manual\n'
                                'Lifecycle: stable\nReview: resolved')
        sections, breaking, markdown = self._compare(resolved)
        self.assertEqual(breaking, [])
        self.assertIn('temporary/monitor → stable/resolved', markdown)

    def test_iana_wording_drift_is_informational(self):
        drifted = BASE.replace('Semantics: Unsigned bignum\n', 'Semantics: Unsigned bignum\nIANA Semantics: Unsigned bignum; see Section 3.4.3\n')
        sections, breaking, markdown = self._compare(drifted)
        self.assertEqual(breaking, [])
        self.assertIn('| cbor_tags.rec | 2 | Unsigned bignum | Unsigned bignum; see Section 3.4.3 |', markdown)

    def test_long_tables_are_folded(self):
        extra = ''.join(f'\nTag: {1000 + i}\nWords: item {i}\nSemantics: Item {i}\nReference:\nSource: heuristic\n'
                        for i in range(report.FOLD_ROWS + 1))
        _, _, markdown = self._compare(BASE + extra)
        self.assertIn(f'<details><summary>{report.FOLD_ROWS + 1} rows</summary>', markdown)


if __name__ == '__main__':
    unittest.main()
