#!/usr/bin/python3
import requests
import csv
import os
import re
import email, time

spacing_string = "  "

iana_coap_c_header_file_path = './c/coap-constants.h'


iana_coap_content_format_cache_file = "./coap/cache/content_formats.csv"
iana_coap_content_format_csv_url = "https://www.iana.org/assignments/core-parameters/content-formats.csv"
iana_coap_content_format_source = "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#content-formats"
iana_coap_content_format_c_typedef_name = "coap_content_format_t"

default_coap_header_c = """
#define COAP_CODE(CLASS, CODE) ((CLASS<<5)|(CODE))
typedef enum {
} coap_code_t;

typedef enum {
} coap_option_number_t;

typedef enum {
} coap_content_format_t;

typedef enum {
} coap_signaling_code_t;

typedef enum {
} coap_signaling_option_t;
"""

###############################################################################
# Download Handler

def download_csv(csv_url: str, cache_file: str):
    response = requests.get(csv_url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch CSV content from {csv_url}")
    csv_content = response.text
    with open(cache_file, "w", encoding="utf-8") as file:
        file.write(csv_content)
    return csv_content

def read_or_download_csv(csv_url: str, cache_file: str):
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

    print(f"Downloading CSV file... ({csv_url}, {cache_file})")
    return download_csv(csv_url, cache_file)


###############################################################################
# C Code Generation Utilities

def search_and_replace_c_typedef_enum(document_content, typename, enum_content):
    pattern = fr'typedef enum \{{([^}}]*)\}} {typename};'
    replacement = f'typedef enum {{\n{enum_content}\n}} {typename};'
    updated_document_content = re.sub(pattern, replacement, document_content, flags=re.DOTALL)
    return updated_document_content


###############################################################################
# Content Format Generation
def coap_content_formats_c_enum_name_generate(content_type: str, content_coding: str):
    """
    This generates a c enum name based on coap content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    content_type = re.sub(r'\s+\(.*\)', '', content_type)
    # Specific handling of known extra parameters
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); charset=([^"]+)', r'\1_\2_\3', content_type)
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); cose-type="cose-([^"]+)"', r'\1_\2_\3', content_type)
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); smime-type=([^"]+)', r'\1_\2_\3', content_type)
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); id=([^"]+)', r'\1_\2_\3', content_type)
    # General handling of unknown parameters
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); [a-zA-Z0-9\-]+="([^"]+)"', r'\1_\2_\3', content_type)
    content_type = re.sub(r'([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\+\.]+); [a-zA-Z0-9\-]+=([^"]+)', r'\1_\2_\3', content_type)
    if content_coding:
        content_type += "_" + content_coding
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = re.sub(r'[^a-zA-Z0-9_]', '_', content_type)
    c_enum_name = c_enum_name.strip('_')
    c_enum_name = c_enum_name.upper()
    return c_enum_name

def coap_content_formats_parse_csv(csv_content: str):
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.reader(csv_lines)
    coap_content_content_format = {}
    for row in csv_reader:
        content_type, content_coding, id_value, reference = map(str.strip, row)
        if content_type.lower() == "content type": # Skip first header
            continue
        if not content_type or not id_value or content_type.lower() == "unassigned" or "reserve" in content_type.lower():
            continue
        if "-" in id_value:
            continue
        coap_content_content_format[int(id_value)] = {
                "c_enum_name": coap_content_formats_c_enum_name_generate(content_type, content_coding),
                "content_type": content_type,
                "content_coding": content_coding,
                "reference": reference
            }
    return coap_content_content_format

def extract_enum_values_from_c_code(c_code: str) -> str:
    match = re.search(r'typedef enum \{([^}]*)\} coap_content_format_t;', c_code, flags=re.DOTALL)
    if not match:
        return {}

    enum_values = {}
    enum_content = match.group(1)
    matches = re.findall(r'(\w+)\s*=\s*(\d+)', enum_content)

    for match in matches:
        enum_name, enum_value = match
        enum_values[int(enum_value)] = enum_name

    return enum_values

def coap_content_formats_existing_header_update(coap_content_content_format):
    existing_enum_name = {}
    with open(iana_coap_c_header_file_path, 'r') as file:
        c_code = file.read()
        existing_enum_name = extract_enum_values_from_c_code(c_code)
        for id_value, row in sorted(existing_enum_name.items()):
            if id_value in coap_content_content_format: # Override
                coap_content_content_format[id_value]["c_enum_name"] = existing_enum_name[id_value]
            else: # Add
                coap_content_content_format[id_value] = {"c_enum_name" : existing_enum_name[id_value]}
    return coap_content_content_format

def iana_coap_content_format_c_header_content(coap_content_content_format):
    c_header_content = ""
    c_header_content += spacing_string + f"/* Autogenerated IANA CoAP Content-Formats (Source: {iana_coap_content_format_source}) */\n"
    for id_value, row in sorted(coap_content_content_format.items()):
        # Extract Fields
        c_enum_name = row.get("c_enum_name", None)
        content_type = row.get("content_type", None)
        content_coding = row.get("content_coding", None)
        reference = row.get("reference", None)
        # Render C header entry
        c_header_line = ""
        if content_type or content_coding or reference:
            c_comment_line = '; '.join(filter(None, [content_type, content_coding, f'Ref: {reference}']))
            c_header_line += spacing_string + f'/* {c_comment_line} */\n'
        c_header_line += spacing_string + f'{c_enum_name.upper()} = {id_value}' + (',\n' if id_value != sorted(coap_content_content_format)[-1] else '')
        c_header_content += c_header_line
    return c_header_content

def iana_coap_content_format_c_typedef_enum_update(header_file_content: str) -> str:
    # Load latest IANA registrations
    csv_content = read_or_download_csv(iana_coap_content_format_csv_url, iana_coap_content_format_cache_file)

    # Parse and process IANA registration into enums
    coap_content_content_format = coap_content_formats_parse_csv(csv_content)

    # Check for existing enum so we do not break it
    coap_content_content_format = coap_content_formats_existing_header_update(coap_content_content_format)

    # Generate enumeration header content
    c_header_content = iana_coap_content_format_c_header_content(coap_content_content_format)

    # Search for coap_content_format_t and replace with new content
    return search_and_replace_c_typedef_enum(header_file_content, iana_coap_content_format_c_typedef_name, c_header_content)

###############################################################################
# Create Header

def iana_coap_c_header_update(iana_coap_c_header_file_path: str):
    # If file doesn't exist yet then write a new file
    if not os.path.exists(iana_coap_c_header_file_path):
        with open(iana_coap_c_header_file_path, 'w+') as file:
            file.write(default_coap_header_c)
    # Update Header
    with open(iana_coap_c_header_file_path, 'r') as file:
        header_file_content = file.read()
    header_file_content = iana_coap_content_format_c_typedef_enum_update(header_file_content)
    with open(iana_coap_c_header_file_path, 'w') as file:
        file.write(header_file_content)
    # Indicate header has been synced
    print(f"C header file '{iana_coap_c_header_file_path}' updated successfully.")

def main():
    iana_coap_c_header_update(iana_coap_c_header_file_path)

if __name__ == "__main__":
    main()
