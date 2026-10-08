#!/usr/bin/env python3
"""
sync.py — fetch IANA registries and append new entries to db/ with empty Words.

Does NO name generation. Run `name.py` afterward to fill Words.
Existing Semantics and Words are never rewritten. Changes to lifecycle-tracked records set Review: pending so `check` blocks generation until they are reviewed.
"""

import argparse
import csv
import io
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import toml

import iana_header_utils as utils
import lifecycle
import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')
cache_dir = os.path.join(script_dir, 'cache')
_snapshot_sources = {}


class SyncError(Exception):
    """A registry produced nothing usable (network, schema change, ...). Never fail silently."""


# ---------------------------------------------------------------------------
# Fetching (XML first, CSV as fallback)
# ---------------------------------------------------------------------------

def _cache_path(subdir, filename):
    path = os.path.join(script_dir, 'cache', subdir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _register_snapshot_source(cache_file, url):
    relative_path = os.path.relpath(cache_file, cache_dir)
    _snapshot_sources[relative_path] = url


def _xml_loader(url, subdir, filename, verbose):
    def load():
        if verbose:
            print(f"  Fetching XML: {url}")
        cache_file = _cache_path(subdir, filename)
        _register_snapshot_source(cache_file, url)
        return utils.read_or_download_xml(url, cache_file)
    return load


def _csv_loader(url, subdir, filename, verbose):
    def load():
        if verbose:
            print(f"  Fetching CSV: {url}")
        cache_file = _cache_path(subdir, filename)
        _register_snapshot_source(cache_file, url)
        content = utils.read_or_download_csv(url, cache_file)
        return list(csv.DictReader(io.StringIO(content)))
    return load


def _write_snapshot(snapshot_dir, snapshot_date=None):
    """Copy only source files used by this sync, plus a URL manifest, into a new dated directory."""
    if not _snapshot_sources:
        raise SyncError('no IANA source files were used; refusing to create an empty snapshot')
    if os.path.exists(snapshot_dir):
        raise SyncError(f'snapshot directory already exists: {snapshot_dir}; snapshots are immutable')

    parent = os.path.dirname(snapshot_dir) or '.'
    os.makedirs(parent, exist_ok=True)
    temporary_dir = tempfile.mkdtemp(prefix='.iana-snapshot-', dir=parent)
    try:
        manifest = [
            f'# IANA source snapshot — {snapshot_date or datetime.now(timezone.utc).date().isoformat()}',
            '',
            'Captured by `python3 c/sync.py --snapshot`. These are the source files used by this sync, copied from `c/cache/` after UTF-8 decoding. The snapshot is immutable; ordinary syncs do not overwrite it.',
            '',
            '| Snapshot file | IANA source |',
            '| --- | --- |',
        ]
        for relative_path, url in sorted(_snapshot_sources.items()):
            cached = os.path.join(cache_dir, relative_path)
            if not os.path.isfile(cached):
                raise SyncError(f'source used by sync is missing from cache: {cached}')
            destination = os.path.join(temporary_dir, relative_path)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copyfile(cached, destination)
            manifest.append(f'| `{relative_path}` | {url} |')

        with open(os.path.join(temporary_dir, 'README.md'), 'w', encoding='utf-8') as output:
            output.write('\n'.join(manifest) + '\n')
        os.rename(temporary_dir, snapshot_dir)
    except SyncError:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise SyncError(f'could not save IANA source snapshot to {snapshot_dir}: {exc}') from exc


def _fetch_entries(label, xml_loader, xml_registry_id, csv_loader, parse_rows):
    """Return parsed entries with tag, semantics, reference, and optional registry metadata.

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
# Row parsing: one function per registry. Each returns (tag, semantics, reference), optionally
# followed by registry-specific fields; parsers also apply the original generator exclusions.
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
        item = _col(row, used_xml, ('data_item', 'description'), 'Data Item')
        sem = _col(row, used_xml, ('semantics', 'description'), 'Semantics')
        ref = _col(row, used_xml, ('xref',), 'Reference')
        if not tag or tag.lower() == 'tag' or '-' in tag or not sem:
            continue
        if 'unassigned' in item.lower() or sem.lower() == 'unassigned' or 'reserved' in sem.lower():
            continue
        if 'earmarked' in sem.lower():
            # Reserved for a future registration by an organisation, e.g. "Earmarked for CoRIM,[draft-...]"
            continue
        out.append((tag, sem, ref, item))
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
        structured_type = _col(row, used_xml, ('structured_type', 'structured', 'type'), 'Structured Type')
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
    return {_key(fname, rec['Tag']): rec
            for rec in recfile.read(db_file) if rec.get('Tag', '').strip()}


def _set_record_field(db_file, tag, field, value):
    """Set one metadata field on an existing record without rewriting its other fields."""
    with open(db_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for start, line in enumerate(lines):
        if not line.startswith('Tag:') or line[4:].strip() != tag:
            continue
        end = start + 1
        while end < len(lines) and lines[end].strip():
            end += 1
        field_prefix = f'{field}:'
        for index in range(start + 1, end):
            if lines[index].startswith(field_prefix):
                lines[index] = f'{field}: {value}\n'
                break
        else:
            source_index = next(
                (index for index in range(start + 1, end) if lines[index].startswith('Source:')),
                end,
            )
            lines.insert(source_index + 1 if source_index < end else end, f'{field}: {value}\n')
        with open(db_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return
    raise SyncError(f"cannot mark {db_file} Tag={tag!r}: record not found")


def _mark_review_pending(db_file, record, dry_run):
    if not dry_run and record.get('Review', '').strip() != 'pending':
        _set_record_field(db_file, record['Tag'].strip(), 'Review', 'pending')
        record['Review'] = 'pending'


def _apply(db_file, rec_type, doc_url, entries, dry_run):
    """Append new entries and mark changed lifecycle entries for review."""
    fname = os.path.basename(db_file)
    if not dry_run:
        recfile.write_header(db_file, rec_type, 'Tag', doc_url)
    existing = _load_existing(db_file)
    added, warnings = [], []

    for entry in entries:
        tag, semantics, reference = entry[:3]
        extra_fields = entry[3:]
        try:
            key = registry.parse_tag(fname, tag)
        except (ValueError, KeyError):
            warnings.append(f"  SKIPPED {fname} Tag {tag!r}: not a valid Tag for this registry")
            continue
        if key in existing:
            record = existing[key]
            old_semantics = record.get('Semantics', '')
            old_lifecycle = record.get('Lifecycle', '').strip() or lifecycle.from_semantics(old_semantics)
            new_lifecycle = lifecycle.from_semantics(semantics)
            semantics_changed = _text(old_semantics) != semantics
            lifecycle_changed = old_lifecycle != new_lifecycle and bool(old_lifecycle or new_lifecycle)

            # References are not compared: XML and CSV renderings differ. A lifecycle entry's
            # semantics/name must be reviewed whenever IANA changes its description or status.
            if semantics_changed:
                warnings.append(
                    f"  UPDATED {fname} Tag {tag}: Semantics changed in IANA\n"
                    f"    db:   {_text(old_semantics)!r}\n"
                    f"    IANA: {semantics!r}"
                )
            if lifecycle_changed or (semantics_changed and (old_lifecycle or new_lifecycle)):
                action = 'would mark' if dry_run else 'marked'
                warnings.append(
                    f"  LIFECYCLE REVIEW {fname} Tag {tag}: "
                    f"{old_lifecycle or 'unmarked'} -> {new_lifecycle or 'stable/unspecified'}; "
                    f"{action} Review: pending"
                )
                _mark_review_pending(db_file, record, dry_run)
            continue  # never rewrite existing Semantics, Words, or References

        record = {
            'Tag': tag,
            'Words': '',
            'Semantics': semantics,
            'Reference': reference,
        }
        if extra_fields and extra_fields[0]:
            record['Data Item'] = extra_fields[0]
        record['Source'] = 'new'
        new_lifecycle = lifecycle.from_semantics(semantics)
        if new_lifecycle:
            record['Lifecycle'] = new_lifecycle
            record['Review'] = 'monitor'
        existing[key] = record
        if not dry_run:
            recfile.append_record(db_file, record)
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
    parser.add_argument('--snapshot', action='store_true', help='Save the source files used by this run in a new dated iana/snapshots directory')
    parser.add_argument('--snapshot-dir', help='Snapshot destination (also enables --snapshot); must not already exist')
    args = parser.parse_args()

    snapshot_dir = None
    snapshot_date = datetime.now(timezone.utc).date().isoformat()
    if args.snapshot or args.snapshot_dir:
        snapshot_dir = os.path.abspath(args.snapshot_dir) if args.snapshot_dir else os.path.join(
            repo_dir, 'iana', 'snapshots', snapshot_date)
        if os.path.exists(snapshot_dir):
            parser.error(f'snapshot directory already exists: {snapshot_dir}; choose another --snapshot-dir')

    _snapshot_sources.clear()
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

        if snapshot_dir:
            _write_snapshot(snapshot_dir, snapshot_date)
            print(f"IANA source snapshot saved to {os.path.relpath(snapshot_dir, repo_dir)}")
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
