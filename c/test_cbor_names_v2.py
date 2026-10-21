"""Tests for the proposed v2 CBOR tag names (IANA fields only)."""

import collections
import unittest

import cbor_names_v2 as v2
import recfile


def _propose(semantics, reference='', data_item='', tag='1'):
    record = {'Tag': tag, 'Semantics': semantics, 'Reference': reference, 'Data Item': data_item}
    slugs = collections.Counter(v2._reference_slugs(reference))
    return v2.propose(record, slugs)[:2]


class CborNamesV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposals, cls.collisions = v2.propose_all(recfile.read(v2.CBOR_TAGS))

    def name(self, tag):
        return self.proposals[tag][0]

    def test_ur_registrations_are_named_by_their_type(self):
        self.assertEqual(_propose('ur:seed, Cryptographic seed'), ('ur seed', 'ur type'))
        self.assertEqual(self.name('40105'), 'ur mldsa signature')
        self.assertEqual(self.name('40803'), 'ur ssh certificate')

    def test_spelled_out_phrase_with_acronym_becomes_the_acronym(self):
        self.assertEqual(self.name('61'), 'cwt')
        self.assertEqual(self.name('266'), 'iri')
        self.assertEqual(self.name('267'), 'iri ref')
        self.assertEqual(self.name('271'), 'dots signal channel object')

    def test_sentence_frames_and_trailing_clauses_are_dropped(self):
        self.assertEqual(self.name('21'), 'expected base64url')
        self.assertEqual(self.name('23'), 'expected base16')
        self.assertEqual(self.name('21607'), 'cbor tag id')
        self.assertEqual(self.name('57343'), 'record structure')
        self.assertEqual(self.name('1330664270'), 'openswan config file')
        self.assertEqual(_propose('JSON Numeric Value, Represented as its JSON Text')[0], 'json numeric value')

    def test_short_comma_attributes_stay_in_the_name(self):
        self.assertEqual(self.name('65'), 'uint16 big endian typed array')
        self.assertEqual(self.name('40'), 'multi dimensional array row major order')
        self.assertEqual(self.name('68'), 'uint8 typed array clamped arithmetic')

    def test_sentence_like_text_uses_a_unique_reference_url_name(self):
        self.assertEqual(self.proposals['20853'], ('quoted', 'reference URL'))
        self.assertEqual(self.name('275'), 'text key map')
        self.assertEqual(self.name('26'), 'perl object')
        self.assertEqual(self.name('259'), 'explicit maps')

    def test_sentence_like_text_falls_back_to_a_name_like_data_item(self):
        paragraph = ('A cryptographically anchored data structure used for digital authorship attestation, capturing '
                     'the authorship process through entangled verifiable delay functions.')
        self.assertEqual(_propose(paragraph, data_item='Proof of Process Packet (PPPP)'),
                         ('proof of process packet', 'Data Item'))

    def test_collisions_are_resolved_with_dropped_detail_but_never_with_references(self):
        self.assertEqual(self.collisions, {})
        self.assertEqual(self.name('108'), 'expected base16 lowercase')
        self.assertEqual(self.name('111'), 'object id')
        self.assertEqual(self.name('112'), 'object id relative to 1 3 6 1 4 1')
        names = ' '.join(words for words, _ in self.proposals.values())
        self.assertNotIn('section', names.split())
        self.assertNotIn('see', names.split())

    def test_manual_names_stand_where_the_rules_collide(self):
        self.assertEqual(self.proposals['65535'], ('invalid 16bit', 'manual (v1)'))
        self.assertEqual(self.proposals['18446744073709551615'], ('invalid 64bit', 'manual (v1)'))

    def test_spec_names_not_in_iana_are_out_of_scope_for_step_1(self):
        # Tag 18 is COSE_Sign1 in RFC 9052, but IANA does not say so; step 2 looks it up in the RFC
        self.assertEqual(self.name('18'), 'cose single signer data object')


if __name__ == '__main__':
    unittest.main()
