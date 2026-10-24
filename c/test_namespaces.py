"""Tests for CBOR tag namespaces (db/namespaces/cbor_tags.rec): assignment, prefixes, and their use in naming."""

import collections
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

import cbor_names_v2
import check
import name
import namespaces
import recfile
import sync

HEADER = '%rec: CborTag\n%key: Tag\n\n'


class NamespaceTableTests(unittest.TestCase):
    def setUp(self):
        self.table = namespaces.load(cbor_names_v2.CBOR_TAGS)

    def test_committed_table_is_valid_and_every_member_is_assigned(self):
        self.assertEqual(namespaces.validate(cbor_names_v2.CBOR_TAGS), [])
        self.assertEqual(set(self.table), {'ur', 'cose', 'suit', 'yang', 'platformv', 'moat'})
        counts = collections.Counter(r.get('Namespace', '').strip() for r in recfile.read(cbor_names_v2.CBOR_TAGS))
        self.assertEqual((counts['ur'], counts['platformv'], counts['cose'], counts['suit']), (49, 13, 8, 2))

    def test_rules_capture_the_items_own_name(self):
        ur, suit = self.table['ur'], self.table['suit']
        self.assertEqual(ur.label({'Semantics': 'ur:ssh-public, Text format SSH public key'}), 'ssh-public')
        self.assertEqual(suit.label({'Semantics': 'SUIT_Report_Protected'}), 'Report_Protected')
        self.assertEqual(self.table['cose'].label({'Semantics': 'COSE Key Set'}), '')

    def test_prefix_is_added_once_and_never_repeated(self):
        cose = self.table['cose']
        self.assertEqual(cose.apply('key set'), 'cose key set')
        self.assertEqual(cose.apply('cose cose key set'), 'cose key set')
        self.assertTrue(cose.has_prefix('cose key set'))
        self.assertFalse(cose.has_prefix('key set cose'))

    def test_validation_reports_broken_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'namespaces'))
            with open(os.path.join(tmp, 'namespaces', 'cbor_tags.rec'), 'w', encoding='utf-8') as f:
                f.write('Namespace: x\nPrefix: X Y\nOrganization: Org\nDescription: d\nSemantics Match: ^(\n\n'
                        'Namespace: x\nPrefix: x\nOrganization: Org\nDescription: d\n')
            with mock.patch.object(namespaces, 'namespaces_dir', os.path.join(tmp, 'namespaces')):
                errors = namespaces.validate(os.path.join(tmp, 'cbor_tags.rec'))
        joined = '\n'.join(errors)
        for expected in ('Prefix must be lowercase', 'not a valid regular expression', 'duplicate Namespace',
                         'needs a Semantics Match or Reference Match'):
            self.assertIn(expected, joined)


class NamespaceInDbTests(unittest.TestCase):
    """Uses a temporary copy of db/ so the real database is never touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'db')
        shutil.copytree(os.path.join(namespaces.db_dir, 'namespaces'), os.path.join(self.db, 'namespaces'))
        self.file = os.path.join(self.db, 'cbor_tags.rec')
        self.patch = mock.patch.object(namespaces, 'namespaces_dir', os.path.join(self.db, 'namespaces'))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write(self, text):
        with open(self.file, 'w', encoding='utf-8') as f:
            f.write(HEADER + text)

    def test_check_requires_assignment_and_prefix(self):
        self.write('Tag: 40300\nWords: seed\nSemantics: ur:seed, Cryptographic seed\nReference:\nSource: manual\n\n'
                   'Tag: 98\nWords: signed data object\nSemantics: COSE Signed Data Object\nReference:\n'
                   'Source: manual\nNamespace: cose\n\n'
                   'Tag: 5\nWords: bigfloat\nSemantics: Bigfloat\nReference:\nSource: manual\nNamespace: nope\n')
        errors = '\n'.join(check.check_file(self.file))
        self.assertIn("Tag='40300': matches namespace 'ur'; add `Namespace: ur`", errors)
        self.assertIn("Tag='98': Words='signed data object' must start with the 'cose' prefix 'cose'", errors)
        self.assertIn("Tag='5': unknown Namespace='nope'", errors)

    def test_assign_adds_the_field_only(self):
        self.write('Tag: 40300\nWords: ur seed\nSemantics: ur:seed, Cryptographic seed\nReference:\nSource: heuristic\n')
        self.assertEqual(namespaces.assign(self.file), [('40300', 'ur')])
        record = recfile.read(self.file)[0]
        self.assertEqual((record['Namespace'], record['Words']), ('ur', 'ur seed'))
        self.assertEqual(check.check_file(self.file), [])

    def test_sync_assigns_new_records(self):
        self.write('')
        sync._apply(self.file, 'CborTag', 'x', [('40999', 'ur:new-thing, A new thing', '[BC]', 'map')], False)
        self.assertEqual(recfile.read(self.file)[0]['Namespace'], 'ur')

    def test_make_name_keeps_the_family_prefix_where_the_text_alone_would_lose_it(self):
        long_ur = ('ur:key-bundle, A bundle of signing and agreement public keys together with the metadata that is '
                   'needed to verify them later')
        self.write(f'Tag: 40998\nWords:\nSemantics: {long_ur}\nReference:\nSource: new\nNamespace: ur\n\n'
                   'Tag: 99998\nWords:\nData Item: Key Set Bundle\nSemantics: A COSE structure that carries several '
                   'keys and the policies that control how each of them may be used by a recipient later on\n'
                   'Reference:\nSource: new\nNamespace: cose\n')
        with redirect_stdout(StringIO()):
            name.fill_words_for_file(self.file)
        words = {r['Tag'].strip(): r['Words'].strip() for r in recfile.read(self.file)}
        # Without namespaces: '' (too long, left for a human) and 'key set bundle' (prefix lost)
        self.assertEqual(words, {'40998': 'ur key bundle', '99998': 'cose key set bundle'})


class NamespaceInV2NamesTests(unittest.TestCase):
    def test_v2_names_use_the_prefix_whatever_the_wording(self):
        table = namespaces.load(cbor_names_v2.CBOR_TAGS)
        slugs = collections.Counter()
        cases = {
            ('ur:mlkem-public-key, The tagged CBOR array containing a key', 'ur'): 'ur mlkem public key',
            ('COSE Key Thumbprint', 'cose'): 'cose key thumbprint',
            ('SUIT_Capability_Report', 'suit'): 'suit capability report',
            ('PlatformV_HAS_CHILD', 'platformv'): 'platformv has child',
        }
        for (semantics, ns), expected in cases.items():
            with self.subTest(semantics=semantics):
                rec = {'Tag': '1', 'Semantics': semantics, 'Reference': ''}
                self.assertEqual(cbor_names_v2.propose(rec, slugs, table[ns])[0], expected)


if __name__ == '__main__':
    unittest.main()
