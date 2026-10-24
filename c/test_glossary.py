"""Tests for the abbreviation glossary written above the CBOR tag enum."""

import os
import tempfile
import unittest

import cbor_names_v2
import glossary


class GlossaryTests(unittest.TestCase):
    def _entries(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'cbor_tags.rec')  # no namespace table next to it: prefixes come from none
            with open(path, 'w', encoding='utf-8') as f:
                f.write('%rec: CborTag\n%key: Tag\n\n' + '\n'.join(
                    f"Tag: {tag}\nWords: {words}\nSemantics: {semantics}\nReference:\nSource: heuristic\n"
                    for tag, words, semantics in records))
            return glossary.entries(path)

    def test_committed_registry_explains_its_families_and_shortenings(self):
        prefixes, acronyms, shortenings = glossary.entries(cbor_names_v2.CBOR_TAGS)
        self.assertEqual([p for p, _ in prefixes], ['COSE', 'MOAT', 'PLATFORMV', 'SUIT', 'UR', 'YANG'])
        self.assertIn('Uniform Resources', dict(prefixes)['UR'])
        self.assertIn('https://github.com/BlockchainCommons', dict(prefixes)['UR'])
        self.assertEqual(dict(acronyms)['CWT'], 'CBOR Web Token')
        self.assertEqual(dict(shortenings)['STRCT'], 'structure / structures')
        self.assertEqual(dict(shortenings)['ID'], 'identifier')

    def test_a_shortening_is_explained_only_where_the_iana_text_has_the_full_word(self):
        _, _, shortenings = self._entries([
            ('1', 'max frame size', 'Max frame size'),         # 'max' is the IANA word itself
            ('2', 'msg digest', 'Message digest'),
        ])
        self.assertEqual(shortenings, [('MSG', 'message')])

    def test_an_acronym_is_explained_only_with_matching_initials(self):
        _, acronyms, _ = self._entries([
            ('1', 'cwt claims', 'CWT claims; see CBOR Web Token (CWT)'),
            ('2', 'xyz thing', 'Some Other Words (XYZ) thing'),
        ])
        self.assertEqual(acronyms, [('CWT', 'CBOR Web Token')])

    def test_comment_is_a_well_formed_c_block(self):
        text = glossary.comment(cbor_names_v2.CBOR_TAGS)
        self.assertTrue(text.startswith('  /* Abbreviations in these names:\n'))
        self.assertTrue(text.endswith('  */\n'))
        self.assertEqual(text.count('*/'), 1)
        self.assertEqual(self._entries([('1', 'binary uuid', 'Binary UUID')]), [[], [], []])


if __name__ == '__main__':
    unittest.main()
