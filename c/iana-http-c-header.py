#!/usr/bin/python3

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
# IANA HTTP C Header Generator

https://github.com/mofosyne/iana-headers

Script Description:

This Python script performs the following tasks:
- Download the latest registry data from IANA for the specified Internet protocol standard if it is outdated or missing in the cache.
- Parse the downloaded data and generate C enumeration values.
- Update or create the C header file with the generated enumeration values, preserving any existing values.
"""

import requests
import csv
import os
import re
import email
import time
import tomllib

spacing_string = "  "

iana_http_c_header_file_path = './src/http-constants.h'
iana_cache_dir_path = './cache/http/'

depreciated_enum_support = True

# Default Source
# This is because this script should be as standalone as possible and the url is unlikely to change
iana_http_status_code_settings = {
    "name"           : "http_status_code",
    "title"          : "IANA HTTP Status Code",
    "csv_url"        : "https://www.iana.org/assignments/http-status-codes/http-status-codes-1.csv",
    "source_url"     : "https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml#http-status-codes-1",
}

iana_http_field_name_settings = {
    "name"           : "http_field_name",
    "title"          : "IANA HTTP Field Name",
    "csv_url"        : "https://www.iana.org/assignments/http-fields/field-names.csv",
    "source_url"     : "https://www.iana.org/assignments/http-fields/http-fields.xhtml#field-names",
}


# Load the iana data sources from the toml file if avaliable
try:
    with open('../iana-sources.toml', 'rb') as config_file:
        config = tomllib.load(config_file)
        iana_http_status_code_settings.update(config.get('iana_http_status_code_settings', {}))
        iana_http_field_name_settings.update(config.get('iana_http_field_name_settings', {}))
        print("Info: IANA Source Settings Config File loaded")
except FileNotFoundError:
    # Handle the case where the toml file doesn't exist
    print("Warning: IANA Source Settings Config File does not exist. Using default settings.")

default_http_header_c = """
// IANA HTTP Headers
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
    match = re.search(fr'typedef enum [^{{]*\{{([^}}]*)\}} {typedef_enum_name};', c_code, flags=re.DOTALL)
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
            if int(enum_value) in enum_values:
                enum_values[int(enum_value)].append(enum_name)
            else:
                enum_values[int(enum_value)] = [enum_name]

        return enum_values

    existing_enum_content = get_content_of_typedef_enum(header_file_content, c_typedef_name)
    existing_enum_name_list = extract_enum_values_from_typedef_enum(header_file_content, existing_enum_content)
    for id_value, existing_enum_name_list_entry in sorted(existing_enum_name_list.items()):
        for existing_enum_name in existing_enum_name_list_entry:
            # Check if we already have a generated value for this existing entry
            if id_value in c_enum_list: # Override
                expected_enum_name = c_enum_list[id_value]["enum_name"]
                # Check if duplicated
                if existing_enum_name != expected_enum_name:
                    # Existing Enum Name Does Not Match With This Name
                    if depreciated_enum_support:
                        # Preserve But Mark As Depreciated / Backward Compatible
                        c_enum_list[id_value]["depreciated_enum_name"] = existing_enum_name
                    else:
                        # Preserve But Override
                        c_enum_list[id_value]["enum_name"] = existing_enum_name
            else: # Add
                c_enum_list[id_value] = {"enum_name" : existing_enum_name}
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
        if "comment" in row:
            c_enum_content += spacing_string + f'// {row.get("comment", "")}\n'
        c_enum_content += spacing_string + f'{row.get("enum_name", "")} = {id_value}'
        if "depreciated_enum_name" in row:
            c_enum_content += ',\n' + spacing_string + f'{row.get("depreciated_enum_name", "")} = {id_value} /* depreciated but identifier kept for backwards compatibility */'
        c_enum_content += (',\n' if id_value != sorted(c_enum_list)[-1] else '\n')

    c_enum_content += range_marker_render(c_range_marker)

    return c_enum_content

def update_c_typedef_enum(document_content, c_typedef_name, c_enum_name, c_head_comment, c_enum_list, c_range_marker = None):
    def search_and_replace_c_typedef_enum(document_content, c_enum_content, typename, enumname = None):
        # Search and replace
        enumname = "" if enumname is None else (enumname + " ")
        pattern = fr'typedef enum [^{{]*\{{([^}}]*)\}} {typename};'
        replacement = f'typedef enum {enumname}{{\n{c_enum_content}}} {typename};'
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
    updated_document_content = search_and_replace_c_typedef_enum(document_content, c_enum_content, c_typedef_name, c_enum_name)

    return updated_document_content

def get_content_of_const_macro(c_code: str, section_name: str) -> str:
    pattern = fr'\/\* Start of {section_name} autogenerated section \*\/(.*?)\/\* End of {section_name} autogenerated section \*\/'
    match = re.search(pattern, c_code, flags=re.DOTALL)
    if not match:
        return None

    return match.group(1)

def update_c_const_macro(document_content, section_name, c_head_comment, c_macro_list):
    def search_and_replace_c_const_macro(document_content, section_name, new_content):
        # Search and replace
        pattern = fr'\/\* Start of {section_name} autogenerated section \*\/(.*?)\n\/\* End of {section_name} autogenerated section \*\/'
        replacement = f'/* Start of {section_name} autogenerated section */\n{new_content}/* End of {section_name} autogenerated section */'
        updated_document_content = re.sub(pattern, replacement, document_content, flags=re.DOTALL)
        return updated_document_content

    # Check if already exist, if not then create one
    if not get_content_of_const_macro(document_content, section_name):
        document_content += f'/* Start of {section_name} autogenerated section */\n'
        document_content += f'/* End of {section_name} autogenerated section */'

    # Generate enumeration header content
    c_const_macro_content = c_head_comment
    for macro_name, macro_data in sorted(c_macro_list.items()):
        c_const_macro_content += f"#define {macro_name} {macro_data.get('value')}"
        if 'comment' in macro_data:
            c_const_macro_content += f" // {macro_data.get('comment')}"
        c_const_macro_content += "\n"

    # Search for typedef enum name and replace with new content
    updated_document_content = search_and_replace_c_const_macro(document_content, section_name, c_const_macro_content)

    return updated_document_content

###############################################################################
# HTTP Status Code Generation
def iana_http_status_codes_c_enum_name_generate(http_status_code: str, semantics: str, typedef_enum_name: str):
    """
    This generates a c enum name based on http content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    semantics = re.sub(r'\s+\(.*\)', '', semantics)
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = f"{typedef_enum_name.upper()}_"+re.sub(r'[^a-zA-Z0-9_]', '_', semantics)
    c_enum_name = c_enum_name.strip('_')
    c_enum_name = c_enum_name.upper()
    return c_enum_name

def iana_http_status_codes_parse_csv(csv_content: str, typedef_enum_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    enum_list = {}
    for row in csv_reader:
        http_status_code = row["Value"]
        description = row["Description"]
        reference = row["Reference"]
        if not http_status_code or description.lower() == "unassigned" or description.lower() == "reserved":
            continue
        if "-" in http_status_code: # is a range of value
            continue
        # Add to enum list
        comment = '; '.join(filter(None, [description, f'Ref: {reference}']))
        enum_name = iana_http_status_codes_c_enum_name_generate(http_status_code, description, typedef_enum_name)
        enum_list[int(http_status_code)] = {"enum_name": enum_name, "comment": comment}
    return enum_list

def iana_http_status_codes_c_typedef_enum_update(header_file_content: str) -> str:
    typedef_enum_name = iana_http_status_code_settings["name"]
    source_name = iana_http_status_code_settings["title"] 
    source_url = iana_http_status_code_settings["source_url"]
    csv_file_url = iana_http_status_code_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"
    c_enum_name = c_typedef_name

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_enum_list = iana_http_status_codes_parse_csv(csv_content, typedef_enum_name)

    # Generate enumeration header content
    c_range_marker = [
        {"start":100, "end":199, "description": "Informational - Request received, continuing process"},
        {"start":200, "end":299, "description": "Success - The action was successfully received, understood, and accepted"},
        {"start":300, "end":399, "description": "Redirection - Further action must be taken in order to complete the request"},
        {"start":400, "end":499, "description": "Client Error - The request contains bad syntax or cannot be fulfilled"},
        {"start":500, "end":599, "description": "Server Error - The server failed to fulfill an apparently valid request"},
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_enum_name, c_head_comment, c_enum_list, c_range_marker)


###############################################################################


def iana_http_field_names_c_macro_name_generate(http_field_names: str, section_name: str):
    """
    This generates a c enum name based on http content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    http_field_names = re.sub(r'\s+\(.*\)', '', http_field_names)
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = f"{section_name.upper()}_"+re.sub(r'[^a-zA-Z0-9_]', '_', http_field_names)
    c_enum_name = c_enum_name.strip('_')
    c_enum_name = c_enum_name.upper()
    return c_enum_name

def iana_http_field_namess_parse_csv(csv_content: str, section_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    c_macro_list = {}
    for row in csv_reader:
        http_field_names = row["Field Name"]
        template = row["Template"]
        status = row["Status"]
        reference = row["Reference"]
        if not http_field_names:
            continue
        # Add to enum list
        comment = '; '.join(filter(None, [http_field_names, template, status, f'Ref: {reference}']))
        macro_name = iana_http_field_names_c_macro_name_generate(http_field_names, section_name)
        c_macro_list[macro_name] = {"value": f"\"{http_field_names}\"", "comment": comment}
    return c_macro_list

def iana_http_field_names_c_const_macro_update(header_file_content: str) -> str:
    section_name = iana_http_field_name_settings["name"]
    source_name = iana_http_field_name_settings["title"] 
    source_url = iana_http_field_name_settings["source_url"]
    csv_file_url = iana_http_field_name_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate head comment
    c_head_comment = f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_macro_list = iana_http_field_namess_parse_csv(csv_content, section_name)

    # Generate enumeration header content
    return update_c_const_macro(header_file_content, section_name, c_head_comment, c_macro_list)


###############################################################################
# Create Header

def iana_http_c_header_update(header_filepath: str):
    # If file doesn't exist yet then write a new file
    os.makedirs(os.path.dirname(header_filepath), exist_ok=True)
    if not os.path.exists(header_filepath):
        with open(header_filepath, 'w+') as file:
            file.write(default_http_header_c)

    # Get latest header content
    with open(header_filepath, 'r') as file:
        header_file_content = file.read()

    # Resync All Values
    header_file_content = iana_http_status_codes_c_typedef_enum_update(header_file_content)
    header_file_content = iana_http_field_names_c_const_macro_update(header_file_content)

    # Write new header content
    with open(header_filepath, 'w') as file:
        file.write(header_file_content)

    # Indicate header has been synced
    print(f"C header file '{header_filepath}' updated successfully.")

def main():
    iana_http_c_header_update(iana_http_c_header_file_path)

if __name__ == "__main__":
    main()
