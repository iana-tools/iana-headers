#!/usr/bin/env python3
"""
generate.py — read db/*.rec and emit C header files.

No network access. No heuristics. Deterministic.
"""

import os
import re
import sys
import argparse
import toml

import recfile
import registry
import iana_header_utils as utils

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')


class GenerateError(Exception):
    """The db cannot be turned into a valid header."""


# Written only when a header does not exist yet; an existing header keeps its own preamble.
HEADER_PREAMBLE = {
    'cbor': """
// IANA CBOR Headers
// Source: https://github.com/mofosyne/iana-headers

""",
    'coap': """
// IANA CoAP Headers
// Source: https://github.com/mofosyne/iana-headers

#define COAP_CODE(CLASS, SUBCLASS) ((((CLASS)&0x07U)<<5)|((SUBCLASS)&0x1FU))
#define COAP_GET_CODE_CLASS(CODE) (((CODE)>>5U)&0x07U)
#define COAP_GET_CODE_SUBCLASS(CODE) ((CODE)&0x1FU)

""",
    'http': """
// IANA HTTP Headers
// Source: https://github.com/mofosyne/iana-headers

""",
}

# Registration procedure ranges, as published by IANA (hardcoded: they change very rarely)
CBOR_SIMPLE_VALUE_RANGES = [
    {"start": 0, "end": 19, "description": "Standards Action"},
    {"start": 32, "end": 255, "description": "Specification Required"},
]
CBOR_TAG_RANGES = [
    {"start": 0, "end": 23, "description": "Standards Action"},
    {"start": 24, "end": 32767, "description": "Specification Required"},
    {"start": 32768, "end": 65535, "description": "First Come First Served (16-bit)"},
    {"start": 65536, "end": 4294967295, "description": "First Come First Served (32-bit)"},
    {"start": 4294967296, "end": 18446744073709551615, "description": "First Come First Served (64-bit)"},
]
# https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#codes
COAP_CODE_RANGES = [
    {"start": 0, "end": 0, "description": "Indicates an Empty message. [RFC7252, section 4.1]"},
    {"start": 1, "end": 31, "description": "Indicates a request. [RFC7252, section 12.1.1]"},
    {"start": 32, "end": 63, "description": "Reserved [RFC7252]"},
    {"start": 64, "end": 191, "description": "Indicates a response. [RFC7252, section 12.1.2]"},
    {"start": 192, "end": 255, "description": "Reserved [RFC7252]"},
]
COAP_OPTION_RANGES = [
    {"start": 0, "end": 255, "description": "IETF Review or IESG Approval"},
    {"start": 256, "end": 2047, "description": "Specification Required"},
    {"start": 2048, "end": 64999, "description": "Expert Review"},
    {"start": 65000, "end": 65535, "description": "Experimental use (no operational use)"},
]
COAP_CONTENT_FORMAT_RANGES = [
    {"start": 0, "end": 255, "description": "Expert Review"},
    {"start": 256, "end": 9999, "description": "IETF Review or IESG Approval"},
    {"start": 10000, "end": 64999, "description": "First Come First Served"},
    {"start": 65000, "end": 65535, "description": "Experimental use (no operational use)"},
]
HTTP_STATUS_CODE_RANGES = [
    {"start": 100, "end": 199, "description": "Informational - Request received, continuing process"},
    {"start": 200, "end": 299, "description": "Success - The action was successfully received, understood, and accepted"},
    {"start": 300, "end": 399, "description": "Redirection - Further action must be taken in order to complete the request"},
    {"start": 400, "end": 499, "description": "Client Error - The request contains bad syntax or cannot be fulfilled"},
    {"start": 500, "end": 599, "description": "Server Error - The server failed to fulfill an apparently valid request"},
]


# ---------------------------------------------------------------------------
# Naming and comment styles
# ---------------------------------------------------------------------------

def words_to_screaming_snake(words_str, prefix):
    """'date time string' + 'cbor_tag' -> 'CBOR_TAG_DATE_TIME_STRING'"""
    inner = '_'.join(words_str.split()).upper()
    return re.sub(r'_{2,}', '_', prefix.upper().rstrip('_') + '_' + inner).strip('_')


def words_to_pascal(words_str):
    """'date time string' -> 'DateTimeString'"""
    return ''.join(w.capitalize() for w in words_str.split())


def _ref(rec):
    ref = rec.get('Reference', '').strip()
    return f'Ref: {ref}' if ref else ''


def _c_comment(text):
    """Text from the db must not be able to end a // or /* */ comment and leak into C code."""
    return text.replace('\r', ' ').replace('\n', ' ').replace('*/', '* /')


def comment_default(rec):
    return _c_comment('; '.join(filter(None, [rec.get('Semantics', ''), _ref(rec)])))


def comment_coap_code(rec):
    tag = rec['Tag'].strip()
    label = registry.coap_class_label(tag)
    return _c_comment('; '.join(filter(None, [f'code: {tag}', f"{label}: {rec.get('Semantics', '')}", _ref(rec)])))


def comment_http_field(rec):
    return _c_comment('; '.join(filter(None, [rec['Tag'].strip(), rec.get('Semantics', ''), _ref(rec)])))


# ---------------------------------------------------------------------------
# db -> enum list builders
# ---------------------------------------------------------------------------

def usable_records(db_file):
    """Records that belong in the header. Anything unnamed is an error, not a silent omission."""
    fname = os.path.basename(db_file)
    if not os.path.exists(db_file):
        raise GenerateError(f"{fname}: not found in db/ (run `make sync`)")
    for rec in recfile.read(db_file):
        source = rec.get('Source', '').strip()
        if source == 'skip':
            continue
        if source in ('new', 'needs-manual') or not rec.get('Words', '').strip():
            raise GenerateError(f"{fname} Tag={rec.get('Tag')!r}: no Words (run `make name`, then `make check`)")
        yield rec


def build_enum_list(db_file, name_fn, comment_fn=comment_default):
    """{key: {"enum_name", "comment"}} for one db file; key is the parsed Tag."""
    fname = os.path.basename(db_file)
    enum_list = {}
    for rec in usable_records(db_file):
        try:
            key = registry.parse_tag(fname, rec['Tag'])
            entry = {"enum_name": name_fn(rec['Words']), "comment": comment_fn(rec)}
        except (ValueError, KeyError) as e:
            raise GenerateError(f"{fname} Tag={rec.get('Tag')!r}: malformed record ({e!r})")
        if key in enum_list:
            raise GenerateError(f"{fname} Tag={rec['Tag']!r}: duplicate Tag")
        enum_list[key] = entry
    return enum_list


def require_entries(enum_list, what):
    if not enum_list:
        raise GenerateError(f"{what}: db has no usable records — an empty C enum is invalid (run `make sync`, `make name`)")
    return enum_list


# ---------------------------------------------------------------------------
# Per-registry generators
# ---------------------------------------------------------------------------

def generate_cbor(header_content, settings, sources):
    cfg = settings['cbor']
    spacing = cfg.get('spacing_string', '  ')
    tiny_cbor = cfg.get('style_override', '') == 'tiny_cbor'

    # Simple values
    name = cfg['simple_value']['name']
    src = sources['iana_cbor_simple_value_source']
    if tiny_cbor:
        typedef = name
        name_fn = lambda words: name + words_to_pascal(words)
    else:
        typedef = f"{name}_t"
        name_fn = lambda words: words_to_screaming_snake(words, name)
    enum_list = require_entries(
        build_enum_list(os.path.join(db_dir, 'cbor_simple_values.rec'), name_fn), 'cbor_simple_values.rec')
    comment = spacing + f"/* Autogenerated {src['title']} (Source: {src['source_url']}) */\n"
    header_content = utils.update_c_typedef_enum(
        header_content, typedef, typedef, comment, enum_list, CBOR_SIMPLE_VALUE_RANGES, spacing_string=spacing)

    # Tags
    name = cfg['tag_source']['name']
    src = sources['iana_cbor_tag_source']
    if tiny_cbor:
        # TinyCBOR style: "CborKnownTags" -> "Cbor" + <Words> + "Tag"
        typedef = name
        known = name.endswith('KnownTags')
        base = name[:-len('KnownTags')] if known else name
        name_fn = lambda words: base + words_to_pascal(words) + ('Tag' if known else '')
    else:
        typedef = f"{name}_t"
        name_fn = lambda words: words_to_screaming_snake(words, name)
    enum_list = require_entries(
        build_enum_list(os.path.join(db_dir, 'cbor_tags.rec'), name_fn), 'cbor_tags.rec')
    names = [e["enum_name"] for e in enum_list.values()]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise GenerateError(f"cbor_tags.rec: duplicate enum names {dupes} (give one of the tags distinct Words)")
    comment = spacing + f"/* Autogenerated {src['title']} (Source: {src['source_url']}) */\n"
    header_content = utils.update_c_typedef_enum(
        header_content, typedef, typedef, comment, enum_list, CBOR_TAG_RANGES, spacing_string=spacing, int_suffix='ULL')

    return header_content


def generate_coap(header_content, settings, sources):
    cfg = settings['coap']
    spacing = cfg.get('spacing_string', '  ')

    # Request + response + signaling codes share one enum
    code_name = cfg['request_response']['name']
    src = sources['iana_coap_request_response_source']
    name_fn = lambda words: words_to_screaming_snake(words, code_name)
    combined = {}
    for kind in ('request', 'response', 'signaling'):
        fname = f'coap_{kind}_codes.rec'
        # each file must contribute: a registry emptied by mistake must not silently vanish from the header
        entries = require_entries(build_enum_list(os.path.join(db_dir, fname), name_fn, comment_coap_code), fname)
        for key, entry in entries.items():
            if key in combined:
                raise GenerateError(f"{fname}: code {key} is already defined by another coap_*_codes.rec file")
            combined[key] = entry
    typedef = f"{code_name}_t"
    comment = spacing + f"/* Autogenerated {src['title']}\n"
    comment += spacing + f"   Request Source: {src['request_source']}\n"
    comment += spacing + f"   Response Source: {src['response_source']}\n"
    comment += spacing + f"   Signaling Source: {src['signaling_source']}\n"
    comment += spacing + "   */\n"
    header_content = utils.update_c_typedef_enum(
        header_content, typedef, typedef, comment, combined, COAP_CODE_RANGES, spacing_string=spacing)

    # Options and content formats
    for key, fname, ranges in (
        ('option', 'coap_options.rec', COAP_OPTION_RANGES),
        ('content_format', 'coap_content_formats.rec', COAP_CONTENT_FORMAT_RANGES),
    ):
        name = cfg[key]['name']
        src = sources[f'iana_coap_{key}_source']
        enum_list = require_entries(
            build_enum_list(os.path.join(db_dir, fname), lambda words, n=name: words_to_screaming_snake(words, n)), fname)
        typedef = f"{name}_t"
        comment = spacing + f"/* Autogenerated {src['title']} (Source: {src['source']}) */\n"
        header_content = utils.update_c_typedef_enum(
            header_content, typedef, typedef, comment, enum_list, ranges, spacing_string=spacing)

    return generate_coap_signaling_options(header_content, settings, sources)


def generate_coap_signaling_options(header_content, settings, sources):
    """One enum per CoAP signaling code, e.g. coap_code_signaling_code_csm_option_number_t."""
    cfg = settings['coap']
    spacing = cfg.get('spacing_string', '  ')
    code_name = cfg['request_response']['name']
    opt_name = cfg['signaling_option_numbers']['name']
    src = sources['iana_coap_signaling_option_numbers_source']

    code_words = {rec['Tag'].strip(): rec['Words'].strip()
                  for rec in usable_records(os.path.join(db_dir, 'coap_signaling_codes.rec'))}

    fname = 'coap_signaling_option_numbers.rec'
    per_code = {}
    for rec in usable_records(os.path.join(db_dir, fname)):
        try:
            code_int, number = registry.parse_tag(fname, rec['Tag'])
        except ValueError as e:
            raise GenerateError(f"{fname} Tag={rec['Tag']!r}: malformed Tag ({e})")
        code = rec['Tag'].strip().rsplit('.', 1)[0]
        if code not in code_words:
            raise GenerateError(f"{fname} Tag={rec['Tag']!r}: {code} is not in coap_signaling_codes.rec")
        short = '_'.join(code_words[code].split())
        entries = per_code.setdefault(code, {"short": short, "enum_list": {}})["enum_list"]
        if number in entries:
            raise GenerateError(f"{fname} Tag={rec['Tag']!r}: duplicate Tag")
        entries[number] = {
            "enum_name": words_to_screaming_snake(rec['Words'], f"{code_name}_{short}_{opt_name}"),
            "comment": comment_default(rec),
        }

    require_entries(per_code, fname)
    for code in sorted(per_code, key=registry.coap_code_to_int):
        short = per_code[code]["short"]
        typedef = f"{code_name}_{short}_{opt_name}_t".lower()
        comment = spacing + (f"/* Autogenerated {src['title']} for CoAP Signaling Code "
                             f"{short.upper()} ({code}) (Source: {src['source']}) */\n")
        header_content = utils.update_c_typedef_enum(
            header_content, typedef, typedef, comment, per_code[code]["enum_list"], spacing_string=spacing)

    return header_content


def generate_http(header_content, settings, sources):
    cfg = settings['http']
    spacing = cfg.get('spacing_string', '  ')

    # Status codes
    name = cfg['http_status_code']['name']
    src = sources['iana_http_status_code_source']
    enum_list = require_entries(
        build_enum_list(os.path.join(db_dir, 'http_status_codes.rec'), lambda words: words_to_screaming_snake(words, name)),
        'http_status_codes.rec')
    typedef = f"{name}_t"
    comment = spacing + f"/* Autogenerated {src['title']} (Source: {src['source_url']}) */\n"
    header_content = utils.update_c_typedef_enum(
        header_content, typedef, typedef, comment, enum_list, HTTP_STATUS_CODE_RANGES, spacing_string=spacing)

    # Field names (X-macro)
    name = cfg['http_field_name']['name']
    src = sources['iana_http_field_name_source']
    fname = 'http_field_names.rec'
    c_macro_list = {}
    for rec in usable_records(os.path.join(db_dir, fname)):
        tag = rec['Tag'].strip()
        if '"' in tag or '\\' in tag:
            raise GenerateError(f"{fname} Tag={tag!r}: cannot be emitted as a C string literal")
        macro_name = words_to_screaming_snake(rec['Words'], name)
        if macro_name in c_macro_list:
            raise GenerateError(f"{fname} Tag={tag!r}: duplicate macro name {macro_name}")
        c_macro_list[macro_name] = {"value": f'"{tag}"', "comment": comment_http_field(rec)}
    require_entries(c_macro_list, fname)
    comment = f"/* Autogenerated {src['title']} (Source: {src['source_url']}) */\n"
    header_content = utils.update_c_const_macro(header_content, name, comment, c_macro_list)

    return header_content


GENERATORS = (
    ('cbor', generate_cbor),
    ('coap', generate_coap),
    ('http', generate_http),
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Generate C headers from db/*.rec')
    parser.add_argument('--sources', default=os.path.join(repo_dir, 'iana_sources.toml'),
                        help='Path to the IANA sources TOML file')
    parser.add_argument('--settings', default=os.path.join(script_dir, 'iana_settings.toml'),
                        help='Path to the IANA settings TOML file')
    args = parser.parse_args()

    try:
        settings = toml.load(args.settings)
        sources = toml.load(args.sources)
    except (FileNotFoundError, toml.TomlDecodeError) as e:
        print(f"ERROR: cannot load config: {e}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(db_dir):
        print("ERROR: db/ not found. Run `make sync` and `make name` first.", file=sys.stderr)
        sys.exit(1)

    # Build every header in memory first so a failure leaves all outputs untouched
    outputs = []
    try:
        for section, generate in GENERATORS:
            path = os.path.join(script_dir, settings[section]['generated_header_filepath'])
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = HEADER_PREAMBLE[section]
            print(f"Generating {os.path.basename(path)} ...")
            outputs.append((path, generate(content, settings, sources)))
    except GenerateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    for path, content in outputs:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    print("Done.")


if __name__ == '__main__':
    main()
