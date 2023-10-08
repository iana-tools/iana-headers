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

import iana_header_utils as utils

spacing_string = "  "

iana_http_c_header_file_path = './src/http-constants.h'
iana_cache_dir_path = './cache/http/'

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
    csv_content = utils.read_or_download_csv(csv_file_url, cache_file_path)

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
    return utils.update_c_typedef_enum(header_file_content, c_typedef_name, c_enum_name, c_head_comment, c_enum_list, c_range_marker)


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
    csv_content = utils.read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    c_macro_list = iana_http_field_namess_parse_csv(csv_content, section_name)

    # Generate enumeration header content
    return utils.update_c_const_macro(header_file_content, section_name, c_head_comment, c_macro_list)


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
