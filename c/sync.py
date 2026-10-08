#!/usr/bin/env python3
"""
sync.py — fetch IANA registries and append new entries to db/ with empty Words.

Does NO name generation. Run `name.py` afterward to fill Words.
Existing records are never rewritten: if IANA changes the Semantics of one, it is only reported.
"""

import os
import re
import csv
import sys
import argparse
import io
import toml

import iana_header_utils as utils
import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')


class SyncError(Exception):
    """A registry produced nothing usable (network, schema change, ...). Never fail silently."""


# ---------------------------------------------------------------------------
# Fetching (XML first, CSV as fallback)
# ---------------------------------------------------------------------------

def _cache_path(subdir, filename):
    path = os.path.join(script_dir, 'cache', subdir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _xml_loader(url, subdir, filename, verbose):
    def load():
        if verbose:
            print(f"  Fetching XML: {url}")
        return utils.read_or_download_xml(url, _cache_path(subdir, filename))
    return load


def _csv_loader(url, subdir, filename, verbose):
    def load():
        if verbose:
            print(f"  Fetching CSV: {url}")
        content = utils.read_or_download_csv(url, _cache_path(subdir, filename))
        return list(csv.DictReader(io.StringIO(content)))
    return load


def _fetch_entries(label, xml_loader, xml_registry_id, csv_loader, parse_rows):
    """Return parsed (tag, semantics, reference) entries.

    XML is preferred, but is only accepted if it yields usable entries: an XML schema that
    differs from what parse_rows expects must fall back to CSV, not silently produce nothing.
    """
    if xml_loader is not None:
        try:
            xml_content = xml_loader()
            records = utils.parse_iana_xml_registry(xml_content, xml_registry_id) if xml_content else []
        except Exception as e:  # network, corrupt cache, malformed XML: all mean "use the CSV"
            print(f"  WARNING: {label}: XML unavailable ({e}), falling back to CSV")
            records = None
        if records is not None:
            entries = parse_rows(records, True) if records else []
            if entries:
                return entries
            if records:
                print(f"  WARNING: {label}: XML registry '{xml_registry_id}' has {len(records)} records but none were "
                      f"usable (element names: {sorted(records[0])}), falling back to CSV")
            else:
                print(f"  WARNING: {label}: XML registry '{xml_registry_id}' not found or empty, falling back to CSV")

    entries = parse_rows(csv_loader(), False)
    if not entries:
        raise SyncError(f"{label}: no usable entries in the XML or the CSV (network blocked? IANA format changed?)")
    return entries


# ---------------------------------------------------------------------------
# Row parsing: one function per registry. Each returns [(tag, semantics, reference), ...]
# and applies the same exclusions the original csv generators did.
# ---------------------------------------------------------------------------

def _text(value):
    """One line, single spaces: a multi-line cell must not be able to corrupt a .rec file."""
    return ' '.join((value or '').split())


def _col(row, used_xml, xml_keys, csv_key):
    if used_xml:
        for key in xml_keys:
            value = _text(row.get(key))
            if value:
                return value
        return ''
    return _text(row.get(csv_key))


def _parse_cbor_simple_values(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value',), 'Value')
        sem = _col(row, used_xml, ('semantics', 'description', 'name'), 'Semantics')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'value' or '-' in tag or not sem:
            continue
        if sem.lower() in ('unassigned', 'reserved'):
            continue
        out.append((tag, sem, ref))
    return out


def _parse_cbor_tags(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value',), 'Tag')
        item = _col(row, used_xml, ('data_item',), 'Data Item')
        sem = _col(row, used_xml, ('semantics', 'description'), 'Semantics')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'tag' or '-' in tag or not sem:
            continue
        if 'unassigned' in item.lower() or sem.lower() == 'unassigned' or 'reserved' in sem.lower():
            continue
        if 'earmarked' in sem.lower():
            # Reserved for a future registration by an organisation, e.g. "Earmarked for CoRIM,[draft-...]"
            continue
        out.append((tag, sem, ref))
    return out


def _parse_coap_codes(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value', 'code'), 'Code')
        sem = _col(row, used_xml, ('name', 'description'), 'Name') or _col(row, used_xml, ('description',), 'Description')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'code' or '-' in tag or not sem:
            continue
        if sem.lower() == 'unassigned':
            continue
        out.append((tag, sem, ref))
    return out


def _parse_coap_options(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value', 'number'), 'Number')
        sem = _col(row, used_xml, ('name', 'description'), 'Name')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'number' or '-' in tag or not sem:
            continue
        if sem.lower() in ('unassigned', 'reserved'):
            continue
        out.append((tag, sem, ref))
    return out


def _parse_coap_content_formats(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value', 'id'), 'ID')
        content_type = _col(row, used_xml, ('content_type', 'name'), 'Content Type')
        coding = _col(row, used_xml, ('content_coding',), 'Content Coding')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'id' or '-' in tag or not content_type:
            continue
        if content_type.lower() == 'unassigned' or 'reserve' in content_type.lower():
            continue
        # Same shape as the published comment: "<media type>; <coding>"
        out.append((tag, '; '.join(filter(None, [content_type, coding])), ref))
    return out


def _make_signaling_option_parser(signaling_codes):
    """Rows apply to one or more signaling codes, or to all of them ("all" / "7.xx")."""
    def parse(rows, used_xml):
        out = []
        for row in rows:
            applies = _col(row, used_xml, ('applies_to',), 'Applies to')
            number = _col(row, used_xml, ('value', 'number'), 'Number')
            sem = _col(row, used_xml, ('name',), 'Name')
            ref = _col(row, used_xml, ('xref',), 'Reference')
            if not applies or not number or number.lower() == 'number' or '-' in number or not sem:
                continue
            if 'unassigned' in sem.lower() or 'reserve' in sem.lower():
                continue
            if 'all' in applies.lower() or '7.xx' in applies.lower():
                codes = signaling_codes
            else:
                codes = [c for c in re.split(r'[,\s]+', applies) if c]
            for code in codes:
                out.append((f'{code}.{number}', sem, ref))
        return out
    return parse


def _parse_http_status_codes(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value',), 'Value')
        sem = _col(row, used_xml, ('description', 'name'), 'Description')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'value' or '-' in tag or not sem:
            continue
        if sem.lower() in ('unassigned', 'reserved') or '(unused)' in sem.lower():
            continue
        out.append((tag, sem, ref))
    return out


def _parse_http_field_names(rows, used_xml):
    out = []
    for row in rows:
        tag = _col(row, used_xml, ('value', 'name', 'field_name'), 'Field Name')
        structured_type = _col(row, used_xml, ('structured_type', 'type'), 'Structured Type')
        status = _col(row, used_xml, ('status',), 'Status')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag:
            continue
        # Same order as the published comment: "<field>; <structured type>; <status>; Ref: ..."
        out.append((tag, '; '.join(filter(None, [structured_type, status])), ref))
    return out


# ---------------------------------------------------------------------------
# db update: append what is new, report what IANA changed
# ---------------------------------------------------------------------------

def _key(fname, tag):
    try:
        return registry.parse_tag(fname, tag)
    except (ValueError, KeyError):
        return tag.strip()


def _load_existing(db_file):
    fname = os.path.basename(db_file)
    return {_key(fname, rec['Tag']): rec.get('Semantics', '')
            for rec in recfile.read(db_file) if rec.get('Tag', '').strip()}


def _apply(db_file, rec_type, doc_url, entries, dry_run):
    """Append entries missing from db_file. Returns (added tags, warnings)."""
    fname = os.path.basename(db_file)
    if not dry_run:
        recfile.write_header(db_file, rec_type, 'Tag', doc_url)
    existing = _load_existing(db_file)
    added, warnings = [], []

    for tag, semantics, reference in entries:
        try:
            key = registry.parse_tag(fname, tag)
        except (ValueError, KeyError):
            warnings.append(f"  SKIPPED {fname} Tag {tag!r}: not a valid Tag for this registry")
            continue
        if key in existing:
            # Words are derived from Semantics, so that is what a human needs to re-review.
            # (References are not compared: the XML and CSV renderings of them differ.)
            if _text(existing[key]) != semantics:
                warnings.append(
                    f"  UPDATED {fname} Tag {tag}: Semantics changed in IANA\n"
                    f"    db:   {_text(existing[key])!r}\n"
                    f"    IANA: {semantics!r}"
                )
            continue  # never rewrite existing records
        existing[key] = semantics
        if not dry_run:
            recfile.append_record(db_file, {
                'Tag': tag,
                'Words': '',
                'Semantics': semantics,
                'Reference': reference,
                'Source': 'new',
            })
        added.append(tag)
    return added, warnings


def _sync_simple(sources, src_key, fname, rec_type, parse_rows, cache_subdir, cache_name, verbose, dry_run):
    src = sources[src_key]
    entries = _fetch_entries(
        fname,
        _xml_loader(src['xml_url'], cache_subdir, f'{cache_name}.xml', verbose) if 'xml_url' in src else None,
        src.get('xml_registry_id', ''),
        _csv_loader(src['csv_url'], cache_subdir, f'{cache_name}.csv', verbose),
        parse_rows,
    )
    return _apply(os.path.join(db_dir, fname), rec_type, src['source_url'], entries, dry_run)


def sync_cbor_tags(sources, verbose=False, dry_run=False):
    return _sync_simple(sources, 'iana_cbor_tag_source', 'cbor_tags.rec', 'CborTag',
                        _parse_cbor_tags, 'cbor', 'cbor-tags', verbose, dry_run)


def sync_cbor_simple_values(sources, verbose=False, dry_run=False):
    return _sync_simple(sources, 'iana_cbor_simple_value_source', 'cbor_simple_values.rec', 'CborSimpleValue',
                        _parse_cbor_simple_values, 'cbor', 'cbor-simple-values', verbose, dry_run)


def sync_http_status_codes(sources, verbose=False, dry_run=False):
    return _sync_simple(sources, 'iana_http_status_code_source', 'http_status_codes.rec', 'HttpStatusCode',
                        _parse_http_status_codes, 'http', 'http-status-codes', verbose, dry_run)


def sync_http_field_names(sources, verbose=False, dry_run=False):
    return _sync_simple(sources, 'iana_http_field_name_source', 'http_field_names.rec', 'HttpFieldName',
                        _parse_http_field_names, 'http', 'http-field-names', verbose, dry_run)


def sync_coap(sources, verbose=False, dry_run=False):
    """All CoAP sub-registries live in one XML file, fetched once per run."""
    xml_src = sources.get('iana_coap_xml_source', {})
    coap_xml = None
    if 'xml_url' in xml_src:
        try:
            coap_xml = _xml_loader(xml_src['xml_url'], 'coap', 'core-parameters.xml', verbose)()
        except Exception as e:
            print(f"  WARNING: CoAP XML unavailable ({e}), using CSV per registry")

    def registry_sync(fname, rec_type, doc_url, registry_id, csv_url, csv_name, parse_rows):
        entries = _fetch_entries(
            fname,
            (lambda: coap_xml) if coap_xml else None,
            registry_id,
            _csv_loader(csv_url, 'coap', csv_name, verbose),
            parse_rows,
        )
        return _apply(os.path.join(db_dir, fname), rec_type, doc_url, entries, dry_run)

    results = {}
    rr = sources['iana_coap_request_response_source']
    for kind in ('request', 'response', 'signaling'):
        results[kind] = registry_sync(
            f'coap_{kind}_codes.rec', f'Coap{kind.capitalize()}Code', rr.get(f'{kind}_source', ''),
            rr.get(f'{kind}_xml_registry_id', ''), rr[f'{kind}_csv_url'], f'coap-{kind}-codes.csv', _parse_coap_codes)

    src = sources['iana_coap_option_source']
    results['option'] = registry_sync(
        'coap_options.rec', 'CoapOption', src.get('source', ''),
        src.get('xml_registry_id', ''), src['csv_url'], 'coap-options.csv', _parse_coap_options)

    src = sources['iana_coap_content_format_source']
    results['content_format'] = registry_sync(
        'coap_content_formats.rec', 'CoapContentFormat', src.get('source', ''),
        src.get('xml_registry_id', ''), src['csv_url'], 'coap-content-formats.csv', _parse_coap_content_formats)

    # Signaling options apply per signaling code ("all" expands to every known signaling code)
    signaling_codes = sorted(
        {rec['Tag'].strip() for rec in recfile.read(os.path.join(db_dir, 'coap_signaling_codes.rec')) if rec.get('Tag')}
        | set(results['signaling'][0]),
        key=registry.coap_code_to_int)
    src = sources['iana_coap_signaling_option_numbers_source']
    results['signaling_option'] = registry_sync(
        'coap_signaling_option_numbers.rec', 'CoapSignalingOption', src.get('source', ''),
        src.get('xml_registry_id', ''), src['csv_url'], 'coap-signaling-options.csv',
        _make_signaling_option_parser(signaling_codes))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Sync IANA registries → db/ (empty Words)')
    parser.add_argument('--sources', default=os.path.join(repo_dir, 'iana_sources.toml'),
                        help='Path to the IANA sources TOML file')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be added without writing')
    parser.add_argument('--verbose', action='store_true', help='Print fetch URLs')
    args = parser.parse_args()

    try:
        sources = toml.load(args.sources)
    except (FileNotFoundError, toml.TomlDecodeError) as e:
        print(f"ERROR: cannot load sources: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        os.makedirs(db_dir, exist_ok=True)

    suffix = " (dry-run)" if args.dry_run else ""
    total_added = 0
    all_warnings = []

    def report(name, result):
        nonlocal total_added
        added, warns = result
        print(f"  {name}: {len(added)} new entries{suffix}")
        if args.verbose:
            for tag in added:
                print(f"    + {tag}")
        total_added += len(added)
        all_warnings.extend(warns)

    try:
        for title, fn in (
            ("CBOR Tags", sync_cbor_tags),
            ("CBOR Simple Values", sync_cbor_simple_values),
        ):
            print(f"=== {title} ===")
            report(title, fn(sources, verbose=args.verbose, dry_run=args.dry_run))

        print("=== CoAP ===")
        for name, result in sync_coap(sources, verbose=args.verbose, dry_run=args.dry_run).items():
            report(name, result)

        for title, fn in (
            ("HTTP Status Codes", sync_http_status_codes),
            ("HTTP Field Names", sync_http_field_names),
        ):
            print(f"=== {title} ===")
            report(title, fn(sources, verbose=args.verbose, dry_run=args.dry_run))
    except SyncError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nTotal new entries: {total_added}")

    if all_warnings:
        print(f"\n{'='*60}")
        print(f"REVIEW NEEDED ({len(all_warnings)}) — IANA differs from db/ (db is never rewritten automatically):")
        for w in all_warnings:
            print(w)

    if total_added > 0 and not args.dry_run:
        print("\nRun `make name` to fill Words for new entries.")


if __name__ == '__main__':
    main()
