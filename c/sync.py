#!/usr/bin/env python3
"""
sync.py — fetch IANA registries and append new entries to db/ with empty Words.

Does NO name generation. Run `name.py` afterward to fill Words.
"""

import os
import csv
import sys
import argparse
import io
import toml
import xml.etree.ElementTree as ET

import iana_header_utils as utils
import recfile

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')

sources = toml.load(os.path.join(repo_dir, 'iana_sources.toml'))


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _cache_path(subdir, filename):
    path = os.path.join(script_dir, 'cache', subdir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def fetch_xml(xml_url, cache_file, verbose=False):
    if verbose:
        print(f"  Fetching XML: {xml_url}")
    return utils.read_or_download_xml(xml_url, cache_file)

def fetch_csv(csv_url, cache_file, verbose=False):
    if verbose:
        print(f"  Fetching CSV: {csv_url}")
    return utils.read_or_download_csv(csv_url, cache_file)

def get_xml_or_csv(source_cfg, xml_url_key, csv_url_key, xml_registry_id_key,
                   cache_subdir, cache_xml_name, cache_csv_name, verbose=False):
    """Try XML first, fall back to CSV. Returns (records_list, used_xml: bool)."""
    if xml_url_key in source_cfg:
        try:
            xml_content = fetch_xml(
                source_cfg[xml_url_key],
                _cache_path(cache_subdir, cache_xml_name),
                verbose=verbose,
            )
            registry_id = source_cfg.get(xml_registry_id_key, '')
            records = utils.parse_iana_xml_registry(xml_content, registry_id)
            if records:
                return records, True
            print(f"  WARNING: XML registry '{registry_id}' empty, falling back to CSV")
        except Exception as e:
            print(f"  WARNING: XML fetch failed ({e}), falling back to CSV")
    csv_content = fetch_csv(
        source_cfg[csv_url_key],
        _cache_path(cache_subdir, cache_csv_name),
        verbose=verbose,
    )
    return list(csv.DictReader(io.StringIO(csv_content))), False


# ---------------------------------------------------------------------------
# Per-registry sync functions
# ---------------------------------------------------------------------------

def _load_existing(db_file):
    """Return dict of Tag → {Semantics, Reference} from an existing rec file."""
    existing = {}
    for rec in recfile.read(db_file):
        tag = rec.get('Tag', '')
        if tag:
            existing[tag] = {'Semantics': rec.get('Semantics', ''), 'Reference': rec.get('Reference', '')}
    return existing

def _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, updated_warnings):
    """Core logic: skip/warn/append for one entry."""
    if tag_str in existing:
        old = existing[tag_str]
        if old['Semantics'] != semantics or old['Reference'] != reference:
            updated_warnings.append(
                f"  UPDATED Tag {tag_str}: semantics or reference changed in IANA\n"
                f"    old semantics: {old['Semantics']!r}\n"
                f"    new semantics: {semantics!r}\n"
                f"    old ref: {old['Reference']!r}\n"
                f"    new ref: {reference!r}"
            )
        return  # never rewrite existing records
    if not dry_run:
        recfile.append_record(db_file, {
            'Tag': tag_str,
            'Words': '',
            'Semantics': semantics,
            'Reference': reference,
            'Source': 'new',
        })
    added.append(tag_str)


def sync_cbor_tags(verbose=False, dry_run=False):
    src = sources['iana_cbor_tag_source']
    db_file = os.path.join(db_dir, 'cbor_tags.rec')
    recfile.write_header(db_file, 'CborTag', 'Tag', src['source_url'])
    existing = _load_existing(db_file)
    added, warnings = [], []

    records, used_xml = get_xml_or_csv(
        src, 'xml_url', 'csv_url', 'xml_registry_id',
        'cbor', 'cbor-tags.xml', 'cbor-tags.csv', verbose=verbose,
    )
    for row in records:
        if used_xml:
            tag_str = row.get('value', '').strip()
            semantics = row.get('description', '').strip()
            reference = row.get('xref', '').strip()
        else:
            tag_str = row.get('Tag', '').strip()
            semantics = row.get('Semantics', '').strip()
            reference = row.get('Reference', '').strip()
        if not tag_str or '-' in tag_str:
            continue
        if not semantics or 'unassigned' in semantics.lower() or 'reserved' in semantics.lower():
            continue
        _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, warnings)

    return added, warnings


def sync_cbor_simple_values(verbose=False, dry_run=False):
    src = sources['iana_cbor_simple_value_source']
    db_file = os.path.join(db_dir, 'cbor_simple_values.rec')
    recfile.write_header(db_file, 'CborSimpleValue', 'Tag', src['source_url'])
    existing = _load_existing(db_file)
    added, warnings = [], []

    records, used_xml = get_xml_or_csv(
        src, 'xml_url', 'csv_url', 'xml_registry_id',
        'cbor', 'cbor-simple-values.xml', 'cbor-simple-values.csv', verbose=verbose,
    )
    for row in records:
        if used_xml:
            tag_str = row.get('value', '').strip()
            semantics = row.get('description', '').strip()
            reference = row.get('xref', '').strip()
        else:
            tag_str = row.get('Value', '').strip()
            semantics = row.get('Semantics', '').strip()
            reference = row.get('Reference', '').strip()
        if not tag_str or '-' in tag_str:
            continue
        if not semantics or 'unassigned' in semantics.lower() or 'reserved' in semantics.lower():
            continue
        _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, warnings)

    return added, warnings


def _sync_coap_registry(db_file, rec_type, doc_url, coap_xml_content, xml_registry_id,
                         csv_url, cache_csv, tag_field, name_field,
                         verbose=False, dry_run=False):
    recfile.write_header(db_file, rec_type, 'Tag', doc_url)
    existing = _load_existing(db_file)
    added, warnings = [], []

    records = None
    if coap_xml_content:
        records = utils.parse_iana_xml_registry(coap_xml_content, xml_registry_id)
    if not records:
        csv_content = fetch_csv(csv_url, cache_csv, verbose=verbose)
        rows = list(csv.DictReader(io.StringIO(csv_content)))
        records = [{tag_field: r.get(tag_field, ''), 'name': r.get(name_field, ''), 'xref': r.get('Reference', '')} for r in rows]
        used_xml = False
    else:
        used_xml = True

    for row in records:
        if used_xml:
            tag_str = row.get('value', '').strip()
            semantics = row.get('name', row.get('description', '')).strip()
            reference = row.get('xref', '').strip()
        else:
            tag_str = row.get(tag_field, '').strip()
            semantics = row.get('name', row.get(name_field, '')).strip()
            reference = row.get('xref', row.get('Reference', '')).strip()
        if not tag_str or '-' in tag_str:
            continue
        if not semantics or 'unassigned' in semantics.lower():
            continue
        _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, warnings)

    return added, warnings


def sync_coap(verbose=False, dry_run=False):
    coap_xml_src = sources.get('iana_coap_xml_source', {})
    coap_xml_content = None
    if 'xml_url' in coap_xml_src:
        try:
            coap_xml_content = fetch_xml(
                coap_xml_src['xml_url'],
                _cache_path('coap', 'core-parameters.xml'),
                verbose=verbose,
            )
        except Exception as e:
            print(f"  WARNING: CoAP XML fetch failed ({e}), will use CSV per-registry")

    src_rr = sources['iana_coap_request_response_source']
    results = {}

    for kind in ('request', 'response', 'signaling'):
        db_file = os.path.join(db_dir, f'coap_{kind}_codes.rec')
        results[kind] = _sync_coap_registry(
            db_file,
            rec_type=f'Coap{kind.capitalize()}Code',
            doc_url=src_rr.get(f'{kind}_source', ''),
            coap_xml_content=coap_xml_content,
            xml_registry_id=src_rr.get(f'{kind}_xml_registry_id', ''),
            csv_url=src_rr.get(f'{kind}_csv_url', ''),
            cache_csv=_cache_path('coap', f'coap-{kind}-codes.csv'),
            tag_field='Code',
            name_field='Name',
            verbose=verbose, dry_run=dry_run,
        )

    src_opt = sources['iana_coap_option_source']
    results['option'] = _sync_coap_registry(
        os.path.join(db_dir, 'coap_options.rec'),
        rec_type='CoapOption',
        doc_url=src_opt.get('source', ''),
        coap_xml_content=coap_xml_content,
        xml_registry_id=src_opt.get('xml_registry_id', ''),
        csv_url=src_opt['csv_url'],
        cache_csv=_cache_path('coap', 'coap-options.csv'),
        tag_field='Number',
        name_field='Name',
        verbose=verbose, dry_run=dry_run,
    )

    src_cf = sources['iana_coap_content_format_source']
    results['content_format'] = _sync_coap_registry(
        os.path.join(db_dir, 'coap_content_formats.rec'),
        rec_type='CoapContentFormat',
        doc_url=src_cf.get('source', ''),
        coap_xml_content=coap_xml_content,
        xml_registry_id=src_cf.get('xml_registry_id', ''),
        csv_url=src_cf['csv_url'],
        cache_csv=_cache_path('coap', 'coap-content-formats.csv'),
        tag_field='ID',
        name_field='Content Type',
        verbose=verbose, dry_run=dry_run,
    )

    src_sig = sources['iana_coap_signaling_option_numbers_source']
    results['signaling_option'] = _sync_coap_registry(
        os.path.join(db_dir, 'coap_signaling_option_numbers.rec'),
        rec_type='CoapSignalingOption',
        doc_url=src_sig.get('source', ''),
        coap_xml_content=coap_xml_content,
        xml_registry_id=src_sig.get('xml_registry_id', ''),
        csv_url=src_sig['csv_url'],
        cache_csv=_cache_path('coap', 'coap-signaling-options.csv'),
        tag_field='Number',
        name_field='Name',
        verbose=verbose, dry_run=dry_run,
    )

    return results


def sync_http_status_codes(verbose=False, dry_run=False):
    src = sources['iana_http_status_code_source']
    db_file = os.path.join(db_dir, 'http_status_codes.rec')
    recfile.write_header(db_file, 'HttpStatusCode', 'Tag', src['source_url'])
    existing = _load_existing(db_file)
    added, warnings = [], []

    records, used_xml = get_xml_or_csv(
        src, 'xml_url', 'csv_url', 'xml_registry_id',
        'http', 'http-status-codes.xml', 'http-status-codes.csv', verbose=verbose,
    )
    for row in records:
        if used_xml:
            tag_str = row.get('value', '').strip()
            semantics = row.get('description', '').strip()
            reference = row.get('xref', '').strip()
        else:
            tag_str = row.get('Value', '').strip()
            semantics = row.get('Description', '').strip()
            reference = row.get('Reference', '').strip()
        if not tag_str or '-' in tag_str:
            continue
        if not semantics or semantics.lower() in ('unassigned', 'reserved') or '(unused)' in semantics.lower():
            continue
        _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, warnings)

    return added, warnings


def sync_http_field_names(verbose=False, dry_run=False):
    src = sources['iana_http_field_name_source']
    db_file = os.path.join(db_dir, 'http_field_names.rec')
    recfile.write_header(db_file, 'HttpFieldName', 'Tag', src['source_url'])
    existing = _load_existing(db_file)
    added, warnings = [], []

    records, used_xml = get_xml_or_csv(
        src, 'xml_url', 'csv_url', 'xml_registry_id',
        'http', 'http-field-names.xml', 'http-field-names.csv', verbose=verbose,
    )
    for row in records:
        if used_xml:
            tag_str = row.get('value', '').strip()
            status = row.get('status', '').strip()
            structured_type = row.get('type', '').strip()
            reference = row.get('xref', '').strip()
            semantics = '; '.join(filter(None, [status, structured_type]))
        else:
            tag_str = row.get('Field Name', '').strip()
            status = row.get('Status', '').strip()
            structured_type = row.get('Structured Type', '').strip()
            reference = row.get('Reference', '').strip()
            semantics = '; '.join(filter(None, [status, structured_type]))
        if not tag_str:
            continue
        _check_and_append(db_file, tag_str, semantics, reference, existing, dry_run, added, warnings)

    return added, warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Sync IANA registries → db/ (empty Words)')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be added without writing')
    parser.add_argument('--verbose', action='store_true', help='Print fetch URLs')
    args = parser.parse_args()

    os.makedirs(db_dir, exist_ok=True)

    total_added = 0
    all_warnings = []

    print("=== CBOR Tags ===")
    added, warns = sync_cbor_tags(verbose=args.verbose, dry_run=args.dry_run)
    print(f"  {len(added)} new entries appended" + (" (dry-run)" if args.dry_run else ""))
    total_added += len(added)
    all_warnings.extend(warns)

    print("=== CBOR Simple Values ===")
    added, warns = sync_cbor_simple_values(verbose=args.verbose, dry_run=args.dry_run)
    print(f"  {len(added)} new entries appended" + (" (dry-run)" if args.dry_run else ""))
    total_added += len(added)
    all_warnings.extend(warns)

    print("=== CoAP ===")
    coap_results = sync_coap(verbose=args.verbose, dry_run=args.dry_run)
    for name, (added, warns) in coap_results.items():
        print(f"  {name}: {len(added)} new entries" + (" (dry-run)" if args.dry_run else ""))
        total_added += len(added)
        all_warnings.extend(warns)

    print("=== HTTP Status Codes ===")
    added, warns = sync_http_status_codes(verbose=args.verbose, dry_run=args.dry_run)
    print(f"  {len(added)} new entries appended" + (" (dry-run)" if args.dry_run else ""))
    total_added += len(added)
    all_warnings.extend(warns)

    print("=== HTTP Field Names ===")
    added, warns = sync_http_field_names(verbose=args.verbose, dry_run=args.dry_run)
    print(f"  {len(added)} new entries appended" + (" (dry-run)" if args.dry_run else ""))
    total_added += len(added)
    all_warnings.extend(warns)

    print(f"\nTotal new entries: {total_added}")

    if all_warnings:
        print(f"\n{'='*60}")
        print(f"IANA UPDATES DETECTED ({len(all_warnings)}) — review whether Words still match:")
        for w in all_warnings:
            print(w)

    if total_added > 0:
        print("\nRun `make name` to fill Words for new entries.")


if __name__ == '__main__':
    main()
