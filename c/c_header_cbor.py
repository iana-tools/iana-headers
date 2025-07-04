#!/usr/bin/env python3

'''
MIT License

Copyright (c) 2023, Brian Khuu
All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

"""
# IANA CBOR C Header Generator

https://github.com/mofosyne/iana-headers

Script Description:

This Python script performs the following tasks:
- Download the latest registry data from IANA for the specified Internet protocol standard if it is outdated or missing in the cache.
- Parse the downloaded data and generate C enumeration values.
- Update or create the C header file with the generated enumeration values, preserving any existing values.
"""

import csv
import os
import re
import toml
import argparse

import iana_header_utils as utils

script_dir = os.path.dirname(__file__)

spacing_string = "  "
iana_cbor_c_header_file_path = './src/cbor_constants.h'
iana_cache_dir_path = './cache/cbor/'

# Override default to tiny cbor compatibility mode (History: https://github.com/intel/tinycbor/issues/240)
tiny_cbor_style_override = False

iana_cbor_settings = {
    "simple_value" : {
        "name" : "cbor_simple_value"
    },
    "tag_source" : {
        "name" : "cbor_tag"
    }
}

# Default Source
# This is because this script should be as standalone as possible and the url is unlikely to change
iana_cbor_simple_value_source = {
    "title"          : "IANA CBOR Content-Formats",
    "csv_url"        : "https://www.iana.org/assignments/cbor-simple-values/simple.csv",
    "source_url"     : "https://www.iana.org/assignments/cbor-simple-values/cbor-simple-values.xhtml#simple",
}

iana_cbor_tag_source = {
    "title"          : "IANA CBOR Tags",
    "csv_url"        : "https://www.iana.org/assignments/cbor-tags/tags.csv",
    "source_url"     : "https://www.iana.org/assignments/cbor-tags/cbor-tags.xhtml#tags",
}

default_cbor_header_c = """
// IANA CBOR Headers
// Source: https://github.com/mofosyne/iana-headers

"""

###############################################################################
# Content Format Generation
def iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value: str, semantics: str, typedef_enum_name: str, camel_case = False):
    """
    This generates a c enum name based on cbor content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    semantics = re.sub(r'\s+\(.*\)', '', semantics)
    variable_name_list = re.sub(r'[^a-zA-Z0-9_]', ' ', semantics).split()

    # Tiny Cbor Style Pascal Case Output
    if camel_case:
        capitalized_variable_name_list = [word.capitalize() for word in variable_name_list]
        pascal_case_str = typedef_enum_name+''.join(capitalized_variable_name_list)
        return pascal_case_str

    # Convert Into Screaming Snake Case Output
    screaming_snake_case_str = f"{typedef_enum_name.upper()}_"+'_'.join(variable_name_list)
    screaming_snake_case_str = screaming_snake_case_str.upper()
    return screaming_snake_case_str

def iana_cbor_simple_values_parse_csv(csv_content: str, typedef_enum_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    enum_list = {}
    for row in csv_reader:
        cbor_simple_value = row["Value"]
        semantics = row["Semantics"]
        reference = row["Reference"]
        if cbor_simple_value.lower() == "value": # Skip first header
            continue
        if not cbor_simple_value or semantics.lower() == "unassigned" or semantics.lower() == "reserved":
            continue
        if "-" in cbor_simple_value: # is a range of value
            continue
        # Add to enum list
        comment = '; '.join(filter(None, [semantics, f'Ref: {reference}']))
        enum_name = ""
        if tiny_cbor_style_override:
            enum_name = iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value, semantics, typedef_enum_name, camel_case=True)
        else:
            enum_name = iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value, semantics, typedef_enum_name)
        enum_list[int(cbor_simple_value)] = {"enum_name": enum_name, "comment": comment}
    return enum_list

def iana_cbor_simple_values_c_typedef_enum_update(header_file_content: str) -> str:
    typedef_enum_name = iana_cbor_settings["simple_value"]["name"]
    source_name = iana_cbor_simple_value_source["title"]
    source_url = iana_cbor_simple_value_source["source_url"]
    csv_file_url = iana_cbor_simple_value_source["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    if tiny_cbor_style_override:
        c_typedef_name = f"{typedef_enum_name}"

    c_enum_name = c_typedef_name

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = utils.read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_enum_list = iana_cbor_simple_values_parse_csv(csv_content, typedef_enum_name)

    # Generate enumeration header content
    c_range_marker = [
        {"start":0, "end":19, "description":"Standards Action"},
        {"start":32, "end":255, "description":"Specification Required"}
        ]
    return utils.update_c_typedef_enum(header_file_content, c_typedef_name, c_enum_name, c_head_comment, c_enum_list, c_range_marker, spacing_string=spacing_string)


###############################################################################
# Content Format Generation

def iana_cbor_tag_c_enum_name_generate(tag_value, semantics, typedef_enum_name, max_words_without_abbreviation = 6):
    def clean_semantics(semantic_str):
        # Handle special edge case e.g. `A confidentiality clearance. The key value pairs of the map are defined in ADatP-4774.4`
        # Handle special edge case e.g. `DDoS Open Threat Signaling (DOTS) signal channel object, as defined in [RFC9132]`
        semantic_str = re.sub(r'[.,].* defined in .*', '', semantic_str)
        # Handle special edge case e.g. `[COSE algorithm identifier, Base Hash value]`
        if (semantics[0] == '[' and semantics[-1] == ']') or (semantics[0] == '(' and semantics[-1] == ')') :
            semantic_str = semantic_str[1:-1]  # Remove the brackets
        # Remove content within parentheses and square brackets
        semantic_str = re.sub(r'\(.*?\)', '', semantic_str)
        semantic_str = re.sub(r'\[.*?\]', '', semantic_str)
        # Clear any straggling )
        semantic_str = re.sub(r'\(', ' ', semantic_str)
        semantic_str = re.sub(r'\)', ' ', semantic_str)
        # Clear any straggling ]
        semantic_str = re.sub(r'\[', ' ', semantic_str)
        semantic_str = re.sub(r'\]', ' ', semantic_str)
        # Clear any extra spaces around
        semantic_str = semantic_str.strip()
        return semantic_str.strip()

    def variable_name_abbreviator(variable_name_list_input, camel_case = False):
        # Split the variable name into words and process each word
        variable_name_list = variable_name_list_input.split()
        variable_name_list = [word.replace('+', 'PLUS') for word in variable_name_list]
        variable_name_list = [word.strip('_') for word in variable_name_list]

        # Strip out 'A' if it's the first word of the list. e.g. "a CBOR Tag identifier"
        if variable_name_list[0] == 'A':
            variable_name_list = variable_name_list[1:]

        processed_variable_name_list = []
        for word in variable_name_list:
            processed_variable_name_list.extend(re.sub(r'\W+', ' ', word).split())

        variable_name_list = processed_variable_name_list

        # Abbreviate most commonly recognised
        very_common_word_abbreviations = {
            "standard": "std",
            "identifier": "id",
            "message": "msg",
            "configuration": "config",
            "reference": "ref",
            "referenced": "ref",
            "previously": "prev",
            # Add more abbreviations as needed
        }
        variable_name_list = [very_common_word_abbreviations.get(term.lower(), term) for term in variable_name_list]

        # Calculate the total character count
        descriptive_total_character_count = sum(len(term) for term in variable_name_list)
        if descriptive_total_character_count >= 40:
            # Apply lossy compression if variable name exceeds reasonable length
            print(f"long semantic tag description detected ({' '.join(variable_name_list)})")
            # Abbreviate common words
            word_abbreviations = {
                "number": "num",
                "complex": "cplx",
                "index": "idx",
                "attribute": "attr",
                "maximum": "max",
                "minimum": "min",
                "communication": "comm",
                "protocol": "proto",
                "information": "info",
                "authentication": "auth",
                "representation": "repr",
                "algorithm": "algo",
                "version": "ver",
                "encoding": "enc",
                "arguments": "arg",
                "object": "obj",
                "language": "lang",
                "independent": "indep",
                "alternatives": "alt",
                "text": "txt",
                "string": "str",
                "integer": "int",
                "signal": "sig",
                "channel": "chn",
                "structure": "strct",
                "structures": "strct",
                "attestation": "attest",
                "identify": "ident",
                "geographic": "geo",
                "geographical": "geo",
                "coordinate": "coord",
                "included": "inc",
                "value": "val",
                "values": "vals",
                "record": "rec",
                "report": "rpt",
                "definition": "def",
                "addressed": "addr",
                "capabilities": "cap",
                "additional": "add",
                "operation": "op",
                "operations": "op",
                "level": "lvl",
                "levels": "lvls",
                "encode": "enc",
                "encoded": "enc",
                "component": "comp",
                "condition": "cond",
                "database": "db",
                "element": "elem",
                "environment": "env",
                "parameter": "param",
                "variable": "var",
                "variables": "var",
                "resource": "res",
                "exception": "excpt",
                "instance": "inst",
                "organization": "org",
                "response": "resp",
                "security": "sec",
                # Add more abbreviations as needed
            }
            variable_name_list = [word_abbreviations.get(term.lower(), term) for term in variable_name_list]
            # Remove common words that don't contribute to the name
            common_words = ["algorithm", "and", "to", "a", "from", "the", "bare"]
            variable_name_list = [term for term in variable_name_list if term.lower() not in common_words]
            print(f"shrunken to ({' '.join(variable_name_list)})")

        # Tiny CBOR Style Pascal Case Output
        if camel_case:
            capitalized_variable_name_list = [word.capitalize() for word in variable_name_list]
            pascal_case_str = ''.join(capitalized_variable_name_list)
            return pascal_case_str

        # Default Macro Name Output as Screaming Snake Case
        screaming_snake_case_str = "_".join(variable_name_list).upper()
        return screaming_snake_case_str

    # Strip out 'A CBOR tag that contains ' in front of a semantic sentence as it's just redundant
    # Dev Note: Was done because of "TCG DICE Endorsement Architecture for Devices" tends to use description of "A CBOR tag that contains X"
    if semantics.startswith("A CBOR tag that contains a "):
        semantics = semantics[len("A CBOR tag that contains a"):]
    elif semantics.startswith("A CBOR tag that contains an "):
        semantics = semantics[len("A CBOR tag that contains an "):]
    elif semantics.startswith("A CBOR tag that contains either "):
        semantics = semantics[len("A CBOR tag that contains either "):]

    # Remove unnecessary '[' and '(' (if not at the beginning)
    semantics = clean_semantics(semantics)

    # Remove descriptions after ':' (if present)
    # Search for colons ':' that are not part of a URI notation
    semantics = re.split(r'(?<!://)(?<!\w:)\s*:\s*(?!\w)', semantics)[0].strip()

    # Remove descriptions after ';' (if present)
    semantics = semantics.split(';', 1)[0].strip()

    # Remove descriptions after '. ' (if present)
    idx = semantics.find(". ")
    if idx != -1:
        semantics = semantics[:idx]

    # Clear any _ to space
    semantics = re.sub(r'\_', ' ', semantics)

    # Clear any - to space
    semantics = re.sub(r'\-', ' ', semantics)

    enum_name = ""
    if tiny_cbor_style_override:
        # Combine tag value and descriptive terms to form the enum name
        enum_name += typedef_enum_name[:-9] if typedef_enum_name.endswith("KnownTags") else typedef_enum_name
        enum_name += variable_name_abbreviator(semantics, camel_case=True)
        if typedef_enum_name.endswith("KnownTags"):
            enum_name += "Tag"
    else:
        # Combine tag value and descriptive terms to form the enum name
        enum_name += f"{typedef_enum_name.upper()}"
        descriptive_terms = variable_name_abbreviator(semantics)
        if descriptive_terms:
            enum_name += "_" + descriptive_terms

        # Cleanup
        # Replace multiple underscores with a single underscore
        enum_name = re.sub(r'_{2,}', '_', enum_name)
        enum_name = enum_name.strip('_')
        enum_name = enum_name.upper()

    return enum_name


def iana_cbor_tag_override_semantic(cbor_tag, semantics):
    # This may be required for edge cases where the variable name generator gets confused by the semantic descriptions

    if "65535" in cbor_tag:
        # 16bit Max Invalid CBOR Tag Marker
        # Always invalid; see Section 10.1,[draft-bormann-cbor-notable-tags-02]
        # The purpose of these tag number registrations is to enable the tag numbers to be reserved for internal use by implementation
        semantics = "invalid 16bit"

    if "4294967295" in cbor_tag:
        # 32bit Max Invalid CBOR Tag Marker
        # Always invalid; see Section 10.1,[draft-bormann-cbor-notable-tags-02]
        # The purpose of these tag number registrations is to enable the tag numbers to be reserved for internal use by implementation
        semantics = "invalid 32bit"

    if "18446744073709551615" in cbor_tag:
        # 64bit Max Invalid CBOR Tag Marker
        # Always invalid; see Section 10.1,[draft-bormann-cbor-notable-tags-02]
        # The purpose of these tag number registrations is to enable the tag numbers to be reserved for internal use by implementation
        semantics = "invalid 64bit"

    if "107" in cbor_tag:
        # SUIT_Envelope as defined in Appendix A of [RFC-ietf-suit-manifest-33]
        semantics = "SUIT Envelope"

    if "1070" in cbor_tag:
        # SUIT_Manifest as defined in Appendix A of [RFC-ietf-suit-manifest-33]
        semantics = "SUIT Manifest"

    if "108" in cbor_tag:
        # Expected conversion to base16 encoding (lowercase)
        # This conflicts with tag 23 because of the 'lowercase' keyword
        semantics = "Expected conversion to base16 encoding lowercase"

    if "527" in cbor_tag:
        # A CBOR tag that contains either: xcorimmap, or signed-xcorim. 
        # This conflicts with the ':' detection heruistic
        semantics = "A CBOR tag that contains either xcorimmap, or signed-xcorim."

    if "554" in cbor_tag or "555" in cbor_tag:
        # Tag 554 and 555 for some reason is both described as
        # 'A CBOR tag that contains a PEM encoded SubjectPublicKeyInfo. See Section 13 of [RFC7468].,[TCG DICE Endorsement Architecture for Devices][TCG Errata for DICE Endorsement Architecture for Devices Version 1.1][TCG],'
        # Possibly a errata? Until it's fixed... best to ban this.
        semantics = None

    return semantics


def iana_cbor_tag_parse_csv(csv_content: str, typedef_enum_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    c_enum_list = {}
    for row in csv_reader:
        cbor_tag = row["Tag"]
        data_item = row["Data Item"]
        semantics = row["Semantics"]
        reference = row["Reference"]
        template = row["Template"] # noqa: F841
        if cbor_tag.lower() == "tag": # Skip first header
            continue
        if not cbor_tag or "unassigned" in data_item.lower() or "reserved" in semantics.lower():
            # Either single unassigned tag or a reserved tag
            continue
        if "earmarked" in semantics.lower():
            # Tag is being reserved for future use by an organisation. 
            # e.g. "Earmarked for CoRIM,[draft-ietf-rats-corim-07]"
            continue
        if "-" in cbor_tag:
            # Range of unassigned tags
            continue

        # Override semantic name description if it doesn't work well with our name generator
        semantics_updated_for_enum_name = iana_cbor_tag_override_semantic(cbor_tag, semantics)
        if semantics_updated_for_enum_name is None:
            # Banned entry (E.g. due to badly worded or duplicated message)
            continue

        # Add to enum list
        enum_name = iana_cbor_tag_c_enum_name_generate(cbor_tag, semantics_updated_for_enum_name, typedef_enum_name)
        comment = '; '.join(filter(None, [semantics, f'Ref: {reference}']))
        c_enum_list[int(cbor_tag)] = {"enum_name": enum_name, "comment": comment}
    return c_enum_list

def iana_cbor_tag_c_typedef_enum_update(header_file_content: str) -> str:
    typedef_enum_name = iana_cbor_settings["tag_source"]["name"]
    source_name = iana_cbor_tag_source["title"]
    source_url = iana_cbor_tag_source["source_url"]
    csv_file_url = iana_cbor_tag_source["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    if tiny_cbor_style_override:
        c_typedef_name = f"{typedef_enum_name}"

    c_enum_name = c_typedef_name

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = utils.read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_enum_list = iana_cbor_tag_parse_csv(csv_content, typedef_enum_name)

    # Include invalid cbor tag flag
    #invalid_tag_enum_name = ""
    #if tiny_cbor_style_override:
    #    # Combine tag value and descriptive terms to form the enum name
    #    invalid_tag_enum_name += typedef_enum_name[:-9] if typedef_enum_name.endswith("KnownTags") else typedef_enum_name
    #    invalid_tag_enum_name += "Invalid"
    #    if typedef_enum_name.endswith("KnownTags"):
    #        invalid_tag_enum_name += "Tag"
    #else:
    #    # Combine tag value and descriptive terms to form the enum name
    #    invalid_tag_enum_name += f"{typedef_enum_name.upper()}_INVALID"
    #c_enum_list[int(18446744073709551615)] = {"enum_name": invalid_tag_enum_name, "comment": comment}

    # Check for duplicate enum names
    enum_names = [entry["enum_name"] for entry in c_enum_list.values()]
    duplicate_enum_names = set([name for name in enum_names if enum_names.count(name) > 1])
    if duplicate_enum_names:
        print(f"Warning: Duplicate enum names detected: {', '.join(duplicate_enum_names)}")
        print(f"Recommend: Update iana_cbor_tag_override_semantic() to handle this specific tag")
        exit(1)

    # Generate enumeration header content
    c_range_marker = [
        {"start": 0, "end": 23, "description": "Standards Action"},
        {"start": 24, "end": 32767, "description": "Specification Required"},
        {"start": 32768, "end": 65535, "description": "First Come First Served (16-bit)"},
        {"start": 65536, "end": 4294967295, "description": "First Come First Served (32-bit)"},
        {"start": 4294967296, "end": 18446744073709551615, "description": "First Come First Served (64-bit)"}
    ]
    header_file_content = utils.update_c_typedef_enum(header_file_content, c_typedef_name, c_enum_name, c_head_comment, c_enum_list, c_range_marker, spacing_string=spacing_string, int_suffix="ULL")

    # Generate constants for cbor tag feature flag
    # Note: Not convinced this is a good idea, so is restricted to tiny cbor compatibility mode
    if tiny_cbor_style_override:
        c_macro_list = {}
        for id_value, row in c_enum_list.items():
            c_macro_list[row["enum_name"]] = {"value": row["enum_name"]}
        header_file_content = utils.update_c_const_macro(header_file_content, "cbor known tag feature flag", "/* #define the constants so we can check with #ifdef */\n", c_macro_list)

    return header_file_content


###############################################################################
# Create Header

def iana_cbor_c_header_update(header_filepath: str):
    # If file doesn't exist yet then write a new file
    os.makedirs(os.path.dirname(header_filepath), exist_ok=True)
    if not os.path.exists(header_filepath):
        with open(header_filepath, 'w+') as file:
            file.write(default_cbor_header_c)

    # Get latest header content
    with open(header_filepath, 'r') as file:
        header_file_content = file.read()

    # Resync All Values
    header_file_content = iana_cbor_simple_values_c_typedef_enum_update(header_file_content)
    header_file_content = iana_cbor_tag_c_typedef_enum_update(header_file_content)

    # Write new header content
    with open(header_filepath, 'w') as file:
        file.write(header_file_content)

    # Indicate header has been synced
    print(f"C header file '{header_filepath}' updated successfully.")

def parse_args():
    parser = argparse.ArgumentParser(description="IANA CBOR C Header Generator")
    parser.add_argument('--sources', default=os.path.join(script_dir, "../iana_sources.toml"),
                        help="Path to the IANA sources TOML file")
    parser.add_argument('--settings', default=os.path.join(script_dir, "iana_settings.toml"),
                        help="Path to the IANA settings TOML file")
    return parser.parse_args()

def main():
    args = parse_args()
    iana_source_filepath = args.sources
    iana_settings_filepath = args.settings

    # Load the iana data sources from the toml file if avaliable
    try:
        with open(iana_source_filepath, 'r') as source_file:
            config = toml.load(source_file)
            iana_cbor_simple_value_source.update(config.get('iana_cbor_simple_value_source', {}))
            iana_cbor_tag_source.update(config.get('iana_cbor_tag_source', {}))
            print("Info: IANA Source Config File loaded")
    except FileNotFoundError:
        # Handle the case where the toml file doesn't exist
        print(f"Warning: IANA Source Config File does not exist. Using default settings. {iana_source_filepath}")

    # Load settings
    try:
        with open(iana_settings_filepath, 'r') as config_file:
            global spacing_string
            global tiny_cbor_style_override

            toml_data = toml.load(config_file)
            cbor_settings = toml_data['cbor']

            spacing_string = cbor_settings.get('spacing_string', spacing_string)
            iana_cbor_c_header_file_path = cbor_settings.get('generated_header_filepath')
            iana_cache_dir_path = cbor_settings.get('cache_directory_path')

            if cbor_settings.get('style_override', None) == "tiny_cbor":
                tiny_cbor_style_override = True

            iana_cbor_settings["simple_value"].update(cbor_settings.get('simple_value', {}))
            iana_cbor_settings["tag_source"].update(cbor_settings.get('tag_source', {}))

            print("Info: IANA Settings Config File loaded")
    except FileNotFoundError:
        # Handle the case where the toml file doesn't exist
        print(f"Warning: IANA Settings Config File does not exist. Using default settings. {iana_settings_filepath}")

    # Path is all relative to this script
    # Note: This approach was chosen to keep things simple, as each project would only have one header file)
    #       (Admittely, if the script location changes, you have to update the settings, but if it's an issue, we can cross that bridge later)
    iana_cbor_c_header_file_path = os.path.join(script_dir, iana_cbor_c_header_file_path)
    iana_cache_dir_path = os.path.join(script_dir, iana_cache_dir_path)


    iana_cbor_c_header_update(iana_cbor_c_header_file_path)

if __name__ == "__main__":
    main()
