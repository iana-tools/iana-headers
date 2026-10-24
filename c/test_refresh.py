"""Tests for the CI-independent IANA update (sync + name + summary)."""

import os
import tempfile
import unittest

import refresh


RECORD = 'Tag: 1\nWords: epoch based date time\nSemantics: Epoch-based date/time\nReference: [RFC8949]\nSource: heuristic\n'
HEADER = '%rec: CborTag\n%key: Tag\n\n'


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'db')
        self.snapshots = os.path.join(self.tmp.name, 'snapshots')
        os.makedirs(self.db)
        with open(os.path.join(self.db, 'cbor_tags.rec'), 'w', encoding='utf-8') as f:
            f.write(HEADER + RECORD)

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_run(self, new_record='', sync_output='Total new entries: 0\n'):
        """Stands in for sync.py/name.py: makes the snapshot dir and optionally appends a named record."""
        calls = []

        def run(script, *args):
            calls.append(script)
            if script == 'sync.py':
                os.makedirs(args[args.index('--snapshot-dir') + 1])
                if new_record:
                    with open(os.path.join(self.db, 'cbor_tags.rec'), 'a', encoding='utf-8') as f:
                        f.write('\n' + new_record)
                return 0, sync_output
            return 0, ''
        return run, calls

    def test_no_changes_discards_the_snapshot(self):
        run, calls = self._fake_run()
        summary, snapshot = refresh.refresh(self.db, self.snapshots, '2026-10-20', run=run)
        self.assertEqual((summary, snapshot), (None, None))
        self.assertEqual(calls, ['sync.py', 'name.py'])
        self.assertEqual(os.listdir(self.snapshots), [])

    def test_changes_produce_a_summary_without_git(self):
        new = ('Tag: 501\nWords: corim map\nSemantics: A CBOR tag that contains a corim-map.\nReference: [TCG]\n'
               'Source: heuristic\nSuggested Words: corim map\nSuggested By: heuristic\n')
        sync_output = ('Total new entries: 1\n\n' + '=' * 60 + '\nREVIEW NEEDED (1) — IANA differs from db/:\n'
                       '  UPDATED cbor_tags.rec Tag 1: Semantics changed in IANA\n\nRun `make name` to fill Words.\n')
        run, _ = self._fake_run(new, sync_output)
        summary, snapshot = refresh.refresh(self.db, self.snapshots, '2026-10-20', intro='From run 7.', run=run)

        self.assertEqual(os.path.basename(snapshot), '2026-10-20')
        self.assertTrue(summary.startswith('From run 7.\n'))
        self.assertIn('`make check` passes', summary)
        self.assertIn('since the previous `db/`', summary)
        self.assertIn('`CBOR_TAG_CORIM_MAP` | heuristic, not reviewed yet', summary)
        self.assertIn('UPDATED cbor_tags.rec Tag 1', summary)
        self.assertNotIn('Run `make name`', summary)

    def test_second_snapshot_on_the_same_day_gets_a_suffix(self):
        os.makedirs(os.path.join(self.snapshots, '2026-10-20'))
        self.assertEqual(os.path.basename(refresh.free_snapshot_dir(self.snapshots, '2026-10-20')), '2026-10-20-2')

    def test_sync_failure_is_an_error(self):
        def run(script, *args):
            return (1, 'ERROR: network') if script == 'sync.py' else (0, '')
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.db, self.snapshots, '2026-10-20', run=run)


if __name__ == '__main__':
    unittest.main()
