"""Regression tests for CBOR semantic name generation."""

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import iana_header_utils as utils
import name
import recfile
import sync


SNAPSHOT_CBOR_TAGS_XML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'iana', 'snapshots', '2026-10-08', 'cbor', 'cbor-tags.xml',
)

# CBOR tags that the 2026-10-08 IANA snapshot added beyond what db/ held at the time.
# '' means the heuristic deliberately leaves the name to a human (`make review`):
# the Semantics is a sentence and the Data Item is only a CBOR type.
SNAPSHOT_2026_10_08_NEW_CBOR_TAG_WORDS = {
    '58': '',
    '60': 'selective disclosure redacted array claim elem',
    '62': '',
    '99': 'cri ref',
    '284': 'json numeric val represented as its json txt',
    '285': 'suit report protected',
    '286': 'suit ref',
    '287': 'suit capability report',
    '501': 'corim map',
    '505': 'conciseswid tag map',
    '506': 'concisemid tag map',
    '526': 'xcorim map',
    '527': 'xcorimmap or signed xcorim',
    '550': 'ueid between 7 and 33 bytes',
    '552': 'sec ver num that is evaluated with equivalence semantics',
    '553': '',
    '556': '',
    '560': 'byte string interpreted as an array of bits',
    '40919': 'concordium smart contract address',
    '44252': '',
    '46010': 'crc 32 iso hdlc digest',
    '46011': 'md5 digest',
    '51997': 'cbor ld',
    '60010': 'numeric expression',
    '60020': 'set of digests expression',
    '60021': 'set of strings expression',
    '133133': 'zewif zcash wallet interchange format document',
    '827539798': 'universal saves format bundle',
    '1347571280': 'proof of process packet',
    '1347571281': 'compact evidence ref',
    '1413829460': 'explicitly none',
    '1463894560': 'writers authenticity report',
    '1735551332': 'promisegrid msg envelope',
}


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

    def test_snapshot_new_cbor_tags_get_reviewed_heuristic_names(self):
        with open(SNAPSHOT_CBOR_TAGS_XML, encoding='utf-8') as source:
            rows = utils.parse_iana_xml_registry(source.read(), 'tags')
        entries = {tag: (semantics, data_item) for tag, semantics, _, data_item in sync._parse_cbor_tags(rows, True)}

        for tag, expected in SNAPSHOT_2026_10_08_NEW_CBOR_TAG_WORDS.items():
            with self.subTest(tag=tag):
                semantics, data_item = entries[tag]
                record = {'Tag': tag, 'Semantics': semantics, 'Data Item': data_item}
                self.assertEqual(name.cbor_tag_words(record), expected)

    def test_article_after_cbor_tag_boilerplate_is_dropped_whole(self):
        self.assertEqual(name.cbor_text_words('A CBOR tag that contains an xcorim-map.'), 'xcorim map')
        self.assertEqual(name.cbor_text_words('A CBOR tag that contains a corim-map.'), 'corim map')

    def test_long_semantics_fall_back_to_a_name_like_data_item(self):
        sentence = ('A cryptographic pointer to a full evidence packet, used for embedding authorship claims '
                    'in space-constrained contexts such as metadata and QR codes.')
        self.assertEqual(
            name.cbor_tag_words({'Tag': '1', 'Semantics': sentence, 'Data Item': 'Compact Evidence Reference'}),
            'compact evidence ref')
        self.assertEqual(name.cbor_tag_words({'Tag': '1', 'Semantics': sentence, 'Data Item': 'byte string'}), '')
        self.assertEqual(name.data_item_name('Writers Authenticity Report (WAR)'), 'Writers Authenticity Report')
        self.assertEqual(name.data_item_name('UTF-8 text string'), '')

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

    def test_interactive_review_offers_numbered_alternatives_and_normalizes_edits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            with open(db_file, 'w', encoding='utf-8') as db:
                db.write(
                    '%rec: CborTag\n%key: Tag\n\n'
                    'Tag: 6\nWords:\nData Item: Proof of Process Packet (PPPP)\n'
                    'Semantics: Packet for authorship\nReference: [IANA]\nSource: new\n\n'
                    'Tag: 7\nWords:\nData Item: array\nSemantics: SUIT_Report_Protected\n'
                    'Reference: [IANA]\nSource: new\n'
                )

            output = StringIO()
            with patch('builtins.input', side_effect=['2', 'e', ' SUIT Report-Protected Envelope ']), redirect_stdout(output):
                issues = name.fill_words_for_file(db_file, interactive=True)

            records = recfile.read(db_file)
            self.assertEqual(issues, [])
            self.assertEqual(records[0]['Words'], 'proof of process packet')
            self.assertEqual(records[1]['Words'], 'suit report protected envelope')
            self.assertEqual({record['Source'] for record in records}, {'manual'})
            self.assertIn('1) packet for authorship  ->  CBOR_TAG_PACKET_FOR_AUTHORSHIP', output.getvalue())
            self.assertIn('2) proof of process packet', output.getvalue())
            self.assertIn('1 accepted, 1 edited, 0 skipped', output.getvalue())

    def test_normalize_words(self):
        self.assertEqual(name.normalize_words(' SUIT Report-Protected '), 'suit report protected')
        self.assertEqual(name.normalize_words('X.509 PEM chain'), 'x 509 pem chain')
        self.assertEqual(name.normalize_words('--'), '')

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
