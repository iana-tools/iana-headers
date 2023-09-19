#!/usr/bin/python3
import requests
import csv
import os
import re
import email, time

spacing_string = "  "

iana_cbor_c_header_file_path = './c/cbor-constants.h'

# NOTE: If you want to add support for other languages, best to refactor these settings as an external json file.
#       Then just copy this file and rename it as iana-cbor-<language>-header.py
#       This is so that other developers could just copy the relevant python script for their language

iana_cbor_simple_value_settings = {
    "c_typedef_name" : "cbor_simple_value_t",
    "name"           : "IANA CBOR Content-Formats",
    "cache_file"     : "./cbor/cache/cbor-simple-values.csv",
    "csv_url"        : "https://www.iana.org/assignments/cbor-simple-values/simple.csv",
    "source"         : "https://www.iana.org/assignments/cbor-simple-values/cbor-simple-values.xhtml#simple",
}

iana_cbor_tag_settings = {
    "c_typedef_name" : "cbor_tag_t",
    "name"           : "IANA CBOR Tags",
    "cache_file"     : "./cbor/cache/tags.csv",
    "csv_url"        : "https://www.iana.org/assignments/cbor-tags/tags.csv",
    "source"         : "https://www.iana.org/assignments/cbor-tags/cbor-tags.xhtml#tags",
}

default_cbor_header_c = """
typedef enum {
} cbor_simple_value_t;

typedef enum {
} cbor_tag_t;
"""


###############################################################################
# Download Handler

def download_csv(csv_url: str, cache_file: str):
    print(f"Downloading CSV file {csv_url} to {cache_file}")
    response = requests.get(csv_url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch CSV content from {csv_url}")
    csv_content = response.text
    with open(cache_file, "w", encoding="utf-8") as file:
        file.write(csv_content)
    return csv_content

def read_or_download_csv(csv_url: str, cache_file: str):
    """
    Load latest IANA registrations
    """
    print(f"Checking {csv_url} (cache:{cache_file})")
    if os.path.exists(cache_file):
        # Cache file already exist. Check if outdated
        response = requests.head(csv_url)
        if 'last-modified' in response.headers:
            remote_last_modified = response.headers['last-modified']
            remote_timestamp = time.mktime(email.utils.parsedate_to_datetime(remote_last_modified).timetuple())
            cached_timestamp = os.path.getmtime(cache_file)
            print(f"remote last modified: {remote_timestamp}")
            print(f"cached last modified: {cached_timestamp}")
            if remote_timestamp <= cached_timestamp:
                # No change detected. Use cached file
                with open(cache_file, "r", encoding="utf-8") as file:
                    csv_content = file.read()
                print("Using cache...")
                return csv_content
            print("Outdated cache...")
        else:
            print("cannot find last modified date time...")
    else:
        print("cache file not found...")
    return download_csv(csv_url, cache_file)


###############################################################################
# C Code Generation Utilities

def extract_enum_values_from_c_code(c_code: str, typedef_enum_name: str) -> str:
    match = re.search(fr'typedef enum \{{([^}}]*)\}} {typedef_enum_name};', c_code, flags=re.DOTALL)
    if not match:
        return {}

    enum_values = {}
    enum_content = match.group(1)
    matches = re.findall(r'(\w+)\s*=\s*(\d+)', enum_content)

    for match in matches:
        enum_name, enum_value = match
        enum_values[int(enum_value)] = enum_name

    return enum_values

def generate_c_enum_content(head_comment, c_enum_list):
    c_enum_content = head_comment
    for id_value, row in sorted(c_enum_list.items()):
        if row["comment"]:
            c_enum_content += spacing_string + f'// {row.get("comment", "")}\n'
        c_enum_content += spacing_string + f'{row.get("c_enum_name", "")} = {id_value}' + (',\n' if id_value != sorted(c_enum_list)[-1] else '')
    return c_enum_content

def search_and_replace_c_typedef_enum(document_content, typename, c_enum_content):
    # Search and replace
    pattern = fr'typedef enum \{{([^}}]*)\}} {typename};'
    replacement = f'typedef enum {{\n{c_enum_content}\n}} {typename};'
    updated_document_content = re.sub(pattern, replacement, document_content, flags=re.DOTALL)
    return updated_document_content

def override_enum_from_existing_typedef_enum(header_file_content, c_enum_list, c_typedef_name: str):
    """
    Check for existing enum so we do not break it
    """
    existing_enum_name = extract_enum_values_from_c_code(header_file_content, c_typedef_name)
    for id_value, row in sorted(existing_enum_name.items()):
        if id_value in c_enum_list: # Override
            c_enum_list[id_value]["c_enum_name"] = existing_enum_name[id_value]
        else: # Add
            c_enum_list[id_value] = {"c_enum_name" : existing_enum_name[id_value]}
    return c_enum_list


###############################################################################
# Content Format Generation
def iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value: str, semantics: str):
    """
    This generates a c enum name based on cbor content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    semantics = re.sub(r'\s+\(.*\)', '', semantics)
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = "CBOR_SIMPLE_VALUE_"+re.sub(r'[^a-zA-Z0-9_]', '_', semantics)
    c_enum_name = c_enum_name.strip('_')
    c_enum_name = c_enum_name.upper()
    return c_enum_name

def iana_cbor_simple_values_parse_csv(csv_content: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.reader(csv_lines)
    cbor_simple_value_list = {}
    for row in csv_reader:
        cbor_simple_value, semantics, reference = map(str.strip, row)
        if cbor_simple_value.lower() == "value": # Skip first header
            continue
        if not cbor_simple_value or semantics.lower() == "unassigned" or semantics.lower() == "reserved":
            continue
        if "-" in cbor_simple_value: # is a range of value
            continue
        cbor_simple_value_list[int(cbor_simple_value)] = {
                "c_enum_name": iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value, semantics),
                "cbor_simple_value": cbor_simple_value,
                "semantics": semantics,
                "reference": reference
            }
    return cbor_simple_value_list

def iana_cbor_simple_values_list_to_c_enum_list(cbor_simple_value):
    c_enum_list = {}
    for id_value, row in sorted(cbor_simple_value.items()):
        # Extract Fields
        c_enum_name = row.get("c_enum_name", None)
        cbor_simple_value = row.get("cbor_simple_value", None)
        semantics = row.get("semantics", None)
        reference = row.get("reference", None)
        # Render C header entry
        c_comment_line = None
        if semantics or reference:
            c_comment_line = '; '.join(filter(None, [semantics, f'Ref: {reference}']))
        # Add to enum list
        c_enum_list[id_value] = {"c_enum_name": c_enum_name, "comment": c_comment_line}
    return c_enum_list

def iana_cbor_simple_values_c_typedef_enum_update(header_file_content: str) -> str:
    # Generate head comment
    source_name = iana_cbor_simple_value_settings["name"]
    source_url = iana_cbor_simple_value_settings["source"]
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(iana_cbor_simple_value_settings["csv_url"], iana_cbor_simple_value_settings["cache_file"])

    # Parse and process IANA registration into enums
    cbor_simple_value_list = iana_cbor_simple_values_parse_csv(csv_content)

    # Check for existing enum so we do not break it
    cbor_simple_value_list = override_enum_from_existing_typedef_enum(header_file_content, cbor_simple_value_list, iana_cbor_simple_value_settings["c_typedef_name"])

    # Format to enum name, value and list
    c_enum_list = iana_cbor_simple_values_list_to_c_enum_list(cbor_simple_value_list)

    # Generate enumeration header content
    c_enum_content = generate_c_enum_content(c_head_comment, c_enum_list)

    # Search for typedef enum name and replace with new content
    c_typedef_name = iana_cbor_simple_value_settings["c_typedef_name"]
    return search_and_replace_c_typedef_enum(header_file_content, c_typedef_name, c_enum_content)


###############################################################################
# Content Format Generation

def iana_cbor_tag_c_enum_name_generate(tag_value, semantics, max_words_without_abbreviation = 6):
    def clean_semantics(semantic_str):
        # Handle special edge case e.g. `A confidentiality clearance. The key value pairs of the map are defined in ADatP-4774.4`
        # Handle special edge case e.g. `DDoS Open Threat Signaling (DOTS) signal channel object, as defined in [RFC9132]`
        semantic_str = re.sub(r'[.,].* defined in .*', '', semantic_str)
        #semantic_str = re.sub(r', as defined in \[RFC\d+\]', '', semantic_str)
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

    # Remove unnecessary '[' and '(' (if not at the beginning)
    semantics = clean_semantics(semantics)

    # Clear any _ to space
    semantics = re.sub(r'\_', ' ', semantics)
    # Clear any - to space
    semantics = re.sub(r'\-', ' ', semantics)

    # Remove descriptions after ':' (if present)
    semantics = semantics.split(':', 1)[0].strip()

    # Remove descriptions after ';' (if present)
    semantics = semantics.split(';', 1)[0].strip()

    # Split the semantics into words and process each word
    descriptive_terms = [re.sub(r'\W+', '_', word.replace('+', 'PLUS')).strip('_') for word in semantics.split()]

    # Calculate the total character count
    descriptive_total_character_count = sum(len(term) for term in descriptive_terms)
    if descriptive_total_character_count >= 40:
        print(f"long semantic tag description detected ({' '.join(descriptive_terms)})")
        # Abbreviate common words
        word_abbreviations = {
            "message": "msg",
            "standard": "std",
            "identifier": "id",
            "number": "num",
            "complex": "cplx",
            "interleaved": "intlv",
            "index": "idx",
            "attribute": "attr",
            "configuration": "config",
            "maximum": "max",
            "minimum": "min",
            "communication": "comm",
            "protocol": "proto",
            "information": "info",
            "authentication": "auth",
            "representation": "repr",
            "resolution": "res",
            "reference": "ref",
            "referenced": "ref",
            "algorithm": "algo",
            "version": "ver",
            "countersignature": "cnt_sig",
            "conversion": "convrt",
            "encoding": "encode",
            "arguments": "arg",
            "object": "obj",
            "language": "lang",
            "independent": "indep",
            "alternatives": "alt",
            "previously": "prev",
            "text": "txt",
            "string": "str",
            "integer": "int",
            "signal": "sig",
            "channel": "chn",
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
            "structure": "strct",
            "report": "rpt",
            "definition": "def",
            "evidence": "evid",
            "addressed": "addr",
            "capabilities": "cap",
            "additional": "add",
            "operation": "op",
            "operations": "op",
            "level": "lvl",
            "indicate": "ind",
            "indicates": "ind",
            # Add more abbreviations as needed
        }
        descriptive_terms = [word_abbreviations.get(term.lower(), term) for term in descriptive_terms]
        # Remove common words that don't contribute to the name
        common_words = ["algorithm", "and", "to", "a", "from", "the", "bare"]
        descriptive_terms = [term for term in descriptive_terms if term.lower() not in common_words]
        print(f"shrunken to ({' '.join(descriptive_terms)})")

    # Combine tag value and descriptive terms to form the enum name
    enum_name = f"CBOR_TAG_{tag_value}"

    if descriptive_terms:
        enum_name += "_" + "_".join(descriptive_terms).upper()

    # Cleanup
    # Replace multiple underscores with a single underscore
    enum_name = re.sub(r'_{2,}', '_', enum_name)
    enum_name = enum_name.strip('_')
    enum_name = enum_name.upper()
    return enum_name


def iana_cbor_tag_parse_csv(csv_content: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.reader(csv_lines)
    cbor_tag_list = {}
    for row in csv_reader:
        cbor_tag, data_item, semantics, reference, template = map(str.strip, row)
        if cbor_tag.lower() == "tag": # Skip first header
            continue
        if not cbor_tag or "unassigned" in data_item.lower() or "reserved" in semantics.lower():
            continue
        if "-" in cbor_tag: # is a range of value
            continue
        cbor_tag_list[int(cbor_tag)] = {
                "c_enum_name": iana_cbor_tag_c_enum_name_generate(cbor_tag, semantics),
                "cbor_tag": cbor_tag,
                "data_item": data_item,
                "semantics": semantics,
                "reference": reference,
                "template": template
            }
    return cbor_tag_list

def iana_cbor_tag_list_to_c_enum_list(cbor_tag):
    c_enum_list = {}
    for id_value, row in sorted(cbor_tag.items()):
        # Extract Fields
        c_enum_name = row.get("c_enum_name", None)
        cbor_tag = row.get("cbor_tag", None)
        semantics = row.get("semantics", None)
        reference = row.get("reference", None)
        # Render C header entry
        c_comment_line = None
        if semantics or reference:
            c_comment_line = '; '.join(filter(None, [semantics, f'Ref: {reference}']))
        # Add to enum list
        c_enum_list[id_value] = {"c_enum_name": c_enum_name, "comment": c_comment_line}
    return c_enum_list

def iana_cbor_tag_c_typedef_enum_update(header_file_content: str) -> str:
    # Generate head comment
    source_name = iana_cbor_tag_settings["name"]
    source_url = iana_cbor_tag_settings["source"]
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(iana_cbor_tag_settings["csv_url"], iana_cbor_tag_settings["cache_file"])

    # Parse and process IANA registration into enums
    cbor_tag_list = iana_cbor_tag_parse_csv(csv_content)

    # Check for existing enum so we do not break it
    cbor_tag_list = override_enum_from_existing_typedef_enum(header_file_content, cbor_tag_list, iana_cbor_tag_settings["c_typedef_name"])

    # Format to enum name, value and list
    c_enum_list = iana_cbor_tag_list_to_c_enum_list(cbor_tag_list)

    # Generate enumeration header content
    c_enum_content = generate_c_enum_content(c_head_comment, c_enum_list)

    # Search for typedef enum name and replace with new content
    c_typedef_name = iana_cbor_tag_settings["c_typedef_name"]
    return search_and_replace_c_typedef_enum(header_file_content, c_typedef_name, c_enum_content)


###############################################################################
# Create Header

def iana_cbor_c_header_update(header_filepath: str):
    # If file doesn't exist yet then write a new file
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

def main():
    iana_cbor_c_header_update(iana_cbor_c_header_file_path)

if __name__ == "__main__":
    main()
