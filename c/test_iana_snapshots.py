"""Offline smoke tests for the checked-in IANA source snapshots."""

import csv
import io
import os
import unittest

import iana_header_utils as utils
import sync


FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'testdata',
    'iana-2026-10-08',
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
