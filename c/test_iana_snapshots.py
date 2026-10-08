"""Offline smoke tests for the checked-in IANA source snapshots."""

import csv
import io
import os
import tempfile
import unittest

import iana_header_utils as utils
import recfile
import sync
from experimental_namer import format_xml_name_fields


FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'iana',
    'snapshots',
    '2026-10-08',
)


def _read_xml(relative_path, registry_id):
    with open(os.path.join(FIXTURE_DIR, relative_path), 'r', encoding='utf-8') as source:
        return utils.parse_iana_xml_registry(source.read(), registry_id)


def _read_csv(relative_path):
    with open(os.path.join(FIXTURE_DIR, relative_path), 'r', encoding='utf-8') as source:
        return list(csv.DictReader(io.StringIO(source.read())))


def _usable_signaling_option_rows(rows, used_xml):
    signaling_rows = _read_xml('coap/core-parameters.xml', 'signaling-codes') if used_xml else _read_csv(
        'coap/coap-signaling-codes.csv'
    )
    signaling_codes = [tag for tag, _, _ in sync._parse_coap_codes(signaling_rows, used_xml)]
    return sync._make_signaling_option_parser(signaling_codes)(rows, used_xml)


class IanaSnapshotTests(unittest.TestCase):
    def test_xml_snapshots_produce_usable_registry_entries(self):
        cases = [
            ('cbor/cbor-simple-values.xml', 'simple', sync._parse_cbor_simple_values),
            ('cbor/cbor-tags.xml', 'tags', sync._parse_cbor_tags),
            ('coap/core-parameters.xml', 'method-codes', sync._parse_coap_codes),
            ('coap/core-parameters.xml', 'response-codes', sync._parse_coap_codes),
            ('coap/core-parameters.xml', 'signaling-codes', sync._parse_coap_codes),
            ('coap/core-parameters.xml', 'option-numbers', sync._parse_coap_options),
            ('http/http-status-codes.xml', 'http-status-codes-1', sync._parse_http_status_codes),
            ('http/http-field-names.xml', 'field-names', sync._parse_http_field_names),
        ]
        for path, registry_id, parser in cases:
            with self.subTest(path=path, registry_id=registry_id):
                rows = _read_xml(path, registry_id)
                self.assertTrue(parser(rows, True))

        content_format_rows = _read_xml('coap/core-parameters.xml', 'content-formats')
        self.assertFalse(sync._parse_coap_content_formats(content_format_rows, True))
        signaling_option_rows = _read_xml('coap/core-parameters.xml', 'signaling-option-numbers')
        self.assertFalse(_usable_signaling_option_rows(signaling_option_rows, True))

    def test_cbor_xml_fields_remain_separate_for_llm_prompt(self):
        rows = _read_xml('cbor/cbor-tags.xml', 'tags')
        record = next(row for row in rows if row.get('value') == '107')

        prompt_fields = format_xml_name_fields(record)

        self.assertIn('Data item/description: map', prompt_fields)
        self.assertIn('Semantics: SUIT_Envelope as defined in Appendix A of', prompt_fields)
        self.assertIn('Reference (citation only):', prompt_fields)

        database_row = next(row for row in sync._parse_cbor_tags(rows, True) if row[0] == '107')
        self.assertEqual(database_row[1], record['semantics'])
        self.assertEqual(database_row[3], record['description'])

    def test_new_cbor_database_records_keep_the_iana_data_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, 'cbor_tags.rec')
            sync._apply(db_file, 'CborTag', 'https://example.test/registry',
                        [('107', 'SUIT_Envelope semantics', '[RFC]', 'map')], False)

            record = recfile.read(db_file)[0]
            self.assertEqual(record['Data Item'], 'map')
            self.assertEqual(record['Semantics'], 'SUIT_Envelope semantics')

    def test_sync_snapshot_captures_only_used_cached_sources_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, 'cache')
            os.makedirs(os.path.join(cache_dir, 'cbor'))
            source_path = os.path.join(cache_dir, 'cbor', 'cbor-tags.xml')
            with open(source_path, 'w', encoding='utf-8') as source:
                source.write('<registry>captured source</registry>')

            old_cache_dir = sync.cache_dir
            old_sources = dict(sync._snapshot_sources)
            snapshot_dir = os.path.join(tmpdir, 'snapshot')
            try:
                sync.cache_dir = cache_dir
                sync._snapshot_sources.clear()
                sync._snapshot_sources['cbor/cbor-tags.xml'] = 'https://www.iana.org/cbor-tags.xml'
                sync._write_snapshot(snapshot_dir)
            finally:
                sync.cache_dir = old_cache_dir
                sync._snapshot_sources.clear()
                sync._snapshot_sources.update(old_sources)

            with open(os.path.join(snapshot_dir, 'cbor', 'cbor-tags.xml'), encoding='utf-8') as saved:
                self.assertEqual(saved.read(), '<registry>captured source</registry>')
            with open(os.path.join(snapshot_dir, 'README.md'), encoding='utf-8') as manifest:
                self.assertIn('https://www.iana.org/cbor-tags.xml', manifest.read())

    def test_http_structured_xml_field_matches_csv_column(self):
        xml_rows = _read_xml('http/http-field-names.xml', 'field-names')
        csv_rows = _read_csv('http/field-names.csv')
        xml_entry = next(row for row in sync._parse_http_field_names(xml_rows, True)
                         if row[0] == 'Activate-Storage-Access')
        csv_entry = next(row for row in sync._parse_http_field_names(csv_rows, False)
                         if row[0] == 'Activate-Storage-Access')

        self.assertEqual(xml_entry, csv_entry)
        self.assertEqual(xml_entry[1], 'Item; provisional')

    def test_csv_fallback_snapshots_produce_usable_registry_entries(self):
        cases = [
            ('cbor/simple.csv', sync._parse_cbor_simple_values),
            ('cbor/tags.csv', sync._parse_cbor_tags),
            ('coap/coap-method-codes.csv', sync._parse_coap_codes),
            ('coap/coap-response-codes.csv', sync._parse_coap_codes),
            ('coap/coap-signaling-codes.csv', sync._parse_coap_codes),
            ('coap/coap-options.csv', sync._parse_coap_options),
            ('coap/coap-content-formats.csv', sync._parse_coap_content_formats),
            ('http/http-status-codes-1.csv', sync._parse_http_status_codes),
            ('http/field-names.csv', sync._parse_http_field_names),
        ]
        for path, parser in cases:
            with self.subTest(path=path):
                rows = _read_csv(path)
                self.assertTrue(parser(rows, False))

        rows = _read_csv('coap/coap-signaling-options.csv')
        self.assertTrue(_usable_signaling_option_rows(rows, False))


if __name__ == '__main__':
    unittest.main()
