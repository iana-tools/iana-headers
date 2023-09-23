#!/usr/bin/python3
import requests
import csv
import os
import re
import email, time

spacing_string = "  "

iana_cbor_c_header_file_path = './c/cbor-constants.h'
iana_cache_dir_path = './cache/'

# NOTE: If you want to add support for other languages, best to refactor these settings as an external json file.
#       Then just copy this file and rename it as iana-cbor-<language>-header.py
#       This is so that other developers could just copy the relevant python script for their language

iana_cbor_simple_value_settings = {
    "c_typedef_name" : "cbor_simple_value_t",
    "name"           : "IANA CBOR Content-Formats",
    "csv_url"        : "https://www.iana.org/assignments/cbor-simple-values/simple.csv",
    "source"         : "https://www.iana.org/assignments/cbor-simple-values/cbor-simple-values.xhtml#simple",
}

iana_cbor_tag_settings = {
    "c_typedef_name" : "cbor_tag_t",
    "name"           : "IANA CBOR Tags",
    "csv_url"        : "https://www.iana.org/assignments/cbor-tags/tags.csv",
    "source"         : "https://www.iana.org/assignments/cbor-tags/cbor-tags.xhtml#tags",
}

default_cbor_header_c = """
// IANA CBOR Headers
// Source: https://github.com/mofosyne/iana-headers

"""


###############################################################################
# Download Handler

def read_or_download_csv(csv_url: str, cache_file: str):
    """
    Load latest IANA registrations
    """
    def download_csv(csv_url: str, cache_file: str):
        print(f"Downloading CSV file {csv_url} to {cache_file}")
        response = requests.get(csv_url)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch CSV content from {csv_url} got http status code {str(response.status_code)}")
        csv_content = response.text
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as file:
            file.write(csv_content)
        return csv_content
    def read_cache_csv(cache_file: str):
        """
        No change detected. Use cached file
        """
        print("Read cache...")
        with open(cache_file, "r", encoding="utf-8") as file:
            return file.read()
        raise Exception(f"Cache file not found {cache_file}")

    print(f"Checking {csv_url} (cache:{cache_file})")

    try:
        if not os.path.exists(cache_file):
            print("cache file not found...")
            return download_csv(csv_url, cache_file)

        # Cache file already exist. Check if outdated
        response = requests.head(csv_url)

        # Check if last modified is still present
        if 'last-modified' not in response.headers:
            print("cannot find last modified date time...")
            return read_cache_csv(cache_file)

        # Get cache and remote timestamp
        remote_last_modified = response.headers['last-modified']
        remote_timestamp = time.mktime(email.utils.parsedate_to_datetime(remote_last_modified).timetuple())
        cached_timestamp = os.path.getmtime(cache_file)
        print(f"remote last modified: {remote_timestamp}")
        print(f"cached last modified: {cached_timestamp}")

        # Check if cache is still valid
        if remote_timestamp <= cached_timestamp:
            print("Cache still valid...")
            return read_cache_csv(cache_file)

        print("Outdated cache...")
        return download_csv(csv_url, cache_file)
    except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as err:
        print(f"An error occurred: {err}")
        if os.path.exists(cache_file):
            return read_cache_csv(cache_file)
        else:
            raise Exception(f"Cache file not found")
    except Exception as e:
        raise Exception(f"An unexpected error occurred: {e}")


###############################################################################
# C Code Generation Utilities

def get_content_of_typedef_enum(c_code: str, typedef_enum_name: str) -> str:
    match = re.search(fr'typedef enum \{{([^}}]*)\}} {typedef_enum_name};', c_code, flags=re.DOTALL)
    if not match:
        return None

    return match.group(1)

def override_enum_from_existing_typedef_enum(header_file_content: str, c_typedef_name: str, c_enum_list):
    """
    Check for existing enum so we do not break it
    """
    def extract_enum_values_from_typedef_enum(c_code: str, existing_enum_content: str) -> str:
        matches = re.findall(r'(\w+)\s*=\s*(\d+)', existing_enum_content)

        enum_values = {}
        for match in matches:
            enum_name, enum_value = match
            enum_values[int(enum_value)] = enum_name

        return enum_values
    existing_enum_content = get_content_of_typedef_enum(header_file_content, c_typedef_name)
    existing_enum_name = extract_enum_values_from_typedef_enum(header_file_content, existing_enum_content)
    for id_value, row in sorted(existing_enum_name.items()):
        if id_value in c_enum_list: # Override
            c_enum_list[id_value]["enum_name"] = existing_enum_name[id_value]
        else: # Add
            c_enum_list[id_value] = {"enum_name" : existing_enum_name[id_value]}
    return c_enum_list

def generate_c_enum_content(c_head_comment, c_enum_list, c_range_marker = None):
    c_range_marker_index = 0
    def range_marker_render(c_range_marker, id_value=None):
        nonlocal c_range_marker_index
        if c_range_marker is None:
            return ''

        range_marker_content = ''
        while c_range_marker_index < len(c_range_marker):
            start_range = c_range_marker[c_range_marker_index].get("start") 
            end_range = c_range_marker[c_range_marker_index].get("end") 
            range_comment = c_range_marker[c_range_marker_index].get("description")
            if id_value is None or start_range <= id_value:
                range_marker_content += '\n' + spacing_string + f'/* {start_range}-{end_range} : {range_comment} */\n'
                c_range_marker_index += 1
                continue
            break

        return range_marker_content

    c_enum_content = c_head_comment

    for id_value, row in sorted(c_enum_list.items()):
        c_enum_content += range_marker_render(c_range_marker, id_value)
        if row["comment"]:
            c_enum_content += spacing_string + f'// {row.get("comment", "")}\n'
        c_enum_content += spacing_string + f'{row.get("enum_name", "")} = {id_value}' + (',\n' if id_value != sorted(c_enum_list)[-1] else '\n')

    c_enum_content += range_marker_render(c_range_marker)

    return c_enum_content

def update_c_typedef_enum(document_content, c_typedef_name, c_head_comment, c_enum_list, c_range_marker = None):
    def search_and_replace_c_typedef_enum(document_content, typename, c_enum_content):
        # Search and replace
        pattern = fr'typedef enum \{{([^}}]*)\}} {typename};'
        replacement = f'typedef enum {{\n{c_enum_content}\n}} {typename};'
        updated_document_content = re.sub(pattern, replacement, document_content, flags=re.DOTALL)
        return updated_document_content

    # Check if already exist, if not then create one
    if not get_content_of_typedef_enum(document_content, c_typedef_name):
        document_content += f'typedef enum {{\n}} {c_typedef_name};\n\n'

    # Old name takes priority for backwards compatibility (unless overridden)
    c_enum_content = override_enum_from_existing_typedef_enum(document_content, c_typedef_name, c_enum_list)

    # Generate enumeration header content
    c_enum_content = generate_c_enum_content(c_head_comment, c_enum_list, c_range_marker)

    # Search for typedef enum name and replace with new content
    updated_document_content = search_and_replace_c_typedef_enum(document_content, c_typedef_name, c_enum_content)

    return updated_document_content


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
        enum_name = iana_cbor_simple_values_c_enum_name_generate(cbor_simple_value, semantics)
        enum_list[int(cbor_simple_value)] = {"enum_name": enum_name, "comment": comment}
    return enum_list

def iana_cbor_simple_values_c_typedef_enum_update(header_file_content: str) -> str:
    source_name = iana_cbor_simple_value_settings["name"]
    source_url = iana_cbor_simple_value_settings["source"]
    c_typedef_name = iana_cbor_simple_value_settings["c_typedef_name"]
    csv_file_url = iana_cbor_simple_value_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_enum_list = iana_cbor_simple_values_parse_csv(csv_content)

    # Generate enumeration header content
    c_range_marker = [
        {"start":0, "end":19, "description":"Standards Action"},
        {"start":32, "end":255, "description":"Specification Required"}
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_head_comment, c_enum_list, c_range_marker)


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

    def variable_name_abbreviator(variable_name_list_input):
        # Split the variable name into words and process each word
        variable_name_list = [re.sub(r'\W+', '_', word.replace('+', 'PLUS')).strip('_') for word in variable_name_list_input.split()]

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

        return "_".join(variable_name_list).upper()

    # Remove unnecessary '[' and '(' (if not at the beginning)
    semantics = clean_semantics(semantics)

    # Remove descriptions after ':' (if present)
    semantics = semantics.split(':', 1)[0].strip()

    # Remove descriptions after ';' (if present)
    semantics = semantics.split(';', 1)[0].strip()

    # Clear any _ to space
    semantics = re.sub(r'\_', ' ', semantics)

    # Clear any - to space
    semantics = re.sub(r'\-', ' ', semantics)

    # Combine tag value and descriptive terms to form the enum name
    enum_name = f"CBOR_TAG_{tag_value}"
    descriptive_terms = variable_name_abbreviator(semantics)
    if descriptive_terms:
        enum_name += "_" + descriptive_terms

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
    csv_reader = csv.DictReader(csv_lines)
    c_enum_list = {}
    for row in csv_reader:
        cbor_tag = row["Tag"]
        data_item = row["Data Item"]
        semantics = row["Semantics"]
        reference = row["Reference"]
        template = row["Template"]
        if cbor_tag.lower() == "tag": # Skip first header
            continue
        if not cbor_tag or "unassigned" in data_item.lower() or "reserved" in semantics.lower():
            continue
        if "-" in cbor_tag: # is a range of value
            continue
        # Add to enum list
        enum_name = iana_cbor_tag_c_enum_name_generate(cbor_tag, semantics)
        comment = '; '.join(filter(None, [semantics, f'Ref: {reference}']))
        c_enum_list[int(cbor_tag)] = {"enum_name": enum_name, "comment": comment}
    return c_enum_list

def iana_cbor_tag_c_typedef_enum_update(header_file_content: str) -> str:
    source_name = iana_cbor_tag_settings["name"]
    source_url = iana_cbor_tag_settings["source"]
    c_typedef_name = iana_cbor_tag_settings["c_typedef_name"]
    csv_file_url = iana_cbor_tag_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_enum_list = iana_cbor_tag_parse_csv(csv_content)

    # Generate enumeration header content
    c_range_marker = [
        {"start":0, "end":23, "description":"Standards Action"},
        {"start":24, "end":32767, "description":"Specification Required"},
        {"start":32768, "end":18446744073709551615, "description":"First Come First Served"}
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_head_comment, c_enum_list, c_range_marker)


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

def main():
    iana_cbor_c_header_update(iana_cbor_c_header_file_path)

if __name__ == "__main__":
    main()
