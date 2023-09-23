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
# IANA CoAP C Header Generator

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
import json

spacing_string = "  "

iana_coap_c_header_file_path = './c/coap-constants.h'
iana_cache_dir_path = './cache/'

# Default Source
# This is because this script should be as standalone as possible and the url is unlikely to change
iana_coap_request_response_settings = {
    "name"                        : "coap_code",
    "title"                       : "IANA CoAP Request/Response",
    # Method
    "request_csv_url"             : "https://www.iana.org/assignments/core-parameters/method-codes.csv",
    "request_source"              : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#method-codes",
    # Response
    "response_csv_url"            : "https://www.iana.org/assignments/core-parameters/response-codes.csv",
    "response_source"             : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#response-codes",
    # Signaling Codes
    "signaling_csv_url"           : "https://www.iana.org/assignments/core-parameters/signaling-codes.csv",
    "signaling_source"            : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#signaling-codes",
}

iana_coap_option_settings = {
    "name"           : "coap_option",
    "title"          : "IANA CoAP Content-Formats",
    "csv_url"        : "https://www.iana.org/assignments/core-parameters/option-numbers.csv",
    "source"         : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#option-numbers",
}

iana_coap_content_format_settings = {
    "name"           : "coap_content_format",
    "title"          : "IANA CoAP Content-Formats",
    "csv_url"        : "https://www.iana.org/assignments/core-parameters/content-formats.csv",
    "source"         : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#content-formats",
}

iana_coap_signaling_option_numbers_settings = {
    "name"           : "option_number",
    "title"          : "IANA CoAP Option Numbers",
    "csv_url"        : "https://www.iana.org/assignments/core-parameters/signaling-option-numbers.csv",
    "source"         : "https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#signaling-option-numbers",
}

# Load the iana data sources from the JSON file if avaliable
try:
    with open('iana-coap-sources.json', 'r') as config_file:
        config = json.load(config_file)
        iana_coap_request_response_settings.update(config.get('iana_coap_request_response_settings', {}))
        iana_coap_option_settings.update(config.get('iana_coap_option_settings', {}))
        iana_coap_content_format_settings.update(config.get('iana_coap_content_format_settings', {}))
        iana_coap_signaling_option_numbers_settings.update(config.get('iana_coap_signaling_option_numbers_settings', {}))
        print("Info: IANA Source Settings Config File loaded")
except FileNotFoundError:
    # Handle the case where the JSON file doesn't exist
    print("Warning: IANA Source Settings Config File does not exist. Using default settings.")

default_cbor_header_c = """
// IANA CoAP Headers
// Source: https://github.com/mofosyne/iana-headers

#define COAP_CODE(CLASS, SUBCLASS) ((((CLASS)&0x07U)<<5)|((SUBCLASS)&0x1FU))
#define COAP_GET_CODE_CLASS(CODE) (((CODE)>>5U)&0x07U)
#define COAP_GET_CODE_SUBCLASS(CODE) ((CODE)&0x1FU)

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
        if "comment" in row:
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
# request response Generation
def iana_coap_code_class_subclass_to_integer(coap_class, coap_subclass):
    return ((((coap_class)&0x07)<<5)|((coap_subclass)&0x1F))

def iana_coap_class_to_str(coap_class):
    if coap_class == 0:
        return "Method"
    if coap_class == 2:
        return "Success"
    if coap_class == 4:
        return "Client Error"
    if coap_class == 5:
        return "Server Error"
    if coap_class == 7:
        return "Signaling Code"
    return "?"

def iana_coap_request_response_c_enum_name_generate(code: str, description: str, typedef_enum_name: str):
    """
    This generates a c enum name based on coap content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    description = re.sub(r'\s+\(.*\)', '', description).strip(' ')
    c_enum_name = f"{typedef_enum_name.upper()}_{code}_{description}"
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = re.sub(r'[^a-zA-Z0-9_]', '_', c_enum_name).strip('_').upper()
    return c_enum_name

def iana_coap_request_response_parse_csv(csv_content: str, typedef_enum_name: str):
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    enum_list = {}
    for row in csv_reader:
        code = row["Code"]
        description = row.get("Name") or row.get("Description")
        reference = row["Reference"]
        if code.lower() == "code": # Skip first header
            continue
        if not code or description.lower() == "unassigned":
            continue
        if "-" in code: # usually indicates an unassigned or reserved range
            continue

        # Extract coap class and subclass
        coap_code_splitted_str = code.split('.')
        coap_class = int(coap_code_splitted_str[0])
        coap_subclass = int(coap_code_splitted_str[1])
        coap_code = iana_coap_code_class_subclass_to_integer(coap_class, coap_subclass)

        # Add to enum list
        enum_name = iana_coap_request_response_c_enum_name_generate(code, description, typedef_enum_name)
        comment_line = '; '.join(filter(None, [f"code: {code}", f"{iana_coap_class_to_str(coap_class)}: {description}",  f'Ref: {reference}']))
        enum_list[int(coap_code)] = {"enum_name": enum_name, "comment": comment_line}
    return enum_list

def iana_coap_request_response_c_typedef_enum_update(header_file_content: str) -> str:
    typedef_enum_name = iana_coap_request_response_settings["name"]
    c_head_comment = ""

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    # Generate head comment
    source_name = iana_coap_request_response_settings["title"]
    request_source_url = iana_coap_request_response_settings["request_source"]
    response_source_url = iana_coap_request_response_settings["response_source"]
    signaling_source_url = iana_coap_request_response_settings["signaling_source"]
    c_head_comment += spacing_string + f"/* Autogenerated {source_name}\n"
    c_head_comment += spacing_string + f"   Request Source: {request_source_url}\n"
    c_head_comment += spacing_string + f"   Response Source: {response_source_url}\n"
    c_head_comment += spacing_string + f"   Signaling Source: {signaling_source_url}\n"
    c_head_comment += spacing_string + f"   */\n"

    # Load latest IANA registrations
    empty_enum_comment_line = '; '.join(filter(None, [f"code: 0.00", f"{iana_coap_class_to_str(0)}: Empty Message", f'Ref: [RFC7252, section 4.1]']))
    coap_empty_enum_list = {0:{
                "enum_name": iana_coap_request_response_c_enum_name_generate("0.00", "Empty Message", typedef_enum_name),
                "comment": empty_enum_comment_line
            }}

    request_csv_file_url = iana_coap_request_response_settings["request_csv_url"]
    request_cache_file_path = iana_cache_dir_path + os.path.basename(request_csv_file_url)
    coap_request_enum_list = iana_coap_request_response_parse_csv(read_or_download_csv(request_csv_file_url, request_cache_file_path), typedef_enum_name)

    response_csv_file_url = iana_coap_request_response_settings["response_csv_url"]
    response_cache_file_path = iana_cache_dir_path + os.path.basename(response_csv_file_url)
    coap_response_enum_list = iana_coap_request_response_parse_csv(read_or_download_csv(response_csv_file_url, response_cache_file_path), typedef_enum_name)

    signaling_csv_file_url = iana_coap_request_response_settings["signaling_csv_url"]
    signaling_cache_file_path = iana_cache_dir_path + os.path.basename(signaling_csv_file_url)
    coap_signaling_enum_list = iana_coap_request_response_parse_csv(read_or_download_csv(signaling_csv_file_url, signaling_cache_file_path), typedef_enum_name)
    
    enum_list = coap_empty_enum_list | coap_request_enum_list | coap_response_enum_list | coap_signaling_enum_list

    # Generate enumeration header content
    # This is specified by https://www.iana.org/assignments/core-parameters/core-parameters.xhtml#codes
    #     however this range marker is intentionally hardcoded to keep this script simple.
    #     This is because it is unlikely this would change in a while and if we do, then this script will
    #     need reworking anyway.
    c_range_marker = [
        {"start":0, "end":0, "description":"Indicates an Empty message. [RFC7252, section 4.1]"},
        {"start":iana_coap_code_class_subclass_to_integer(0,1), "end":iana_coap_code_class_subclass_to_integer(0,31), "description":"Indicates a request. [RFC7252, section 12.1.1]"},
        {"start":iana_coap_code_class_subclass_to_integer(1,0), "end":iana_coap_code_class_subclass_to_integer(1,31), "description":"Reserved [RFC7252]"},
        {"start":iana_coap_code_class_subclass_to_integer(2,0), "end":iana_coap_code_class_subclass_to_integer(5,31), "description":"Indicates a response. [RFC7252, section 12.1.2]"},
        {"start":iana_coap_code_class_subclass_to_integer(6,0), "end":iana_coap_code_class_subclass_to_integer(7,31), "description":"Reserved [RFC7252]"},
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_head_comment, enum_list, c_range_marker)



###############################################################################
# CoAP Option Number Generation

def iana_coap_option_enum_name_generate(option_number: str, option_name: str, typedef_enum_name: str):
    """
    This generates a c enum name based on coap content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    option_name = re.sub(r'\s+\(.*\)', '', option_name).strip(' ')
    c_enum_name = f"{typedef_enum_name.upper()}_{option_name}"
    # Convert non alphanumeric characters into variable name friendly underscore
    c_enum_name = re.sub(r'[^a-zA-Z0-9_]', '_', c_enum_name).strip('_').upper()
    return c_enum_name

def iana_coap_option_parse_csv(csv_content: str, typedef_enum_name: str):
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    enum_list = {}
    for row in csv_reader:
        option_number = row["Number"]
        option_name = row["Name"]
        reference = row["Reference"]
        if option_number.lower() == "number": # Skip first header
            continue
        if not option_number or option_name.lower() == "unassigned" or option_name.lower() == "reserved":
            continue
        if "-" in option_number: # usually indicates an unassigned or reserved range
            continue

        # Add to enum list
        enum_name = iana_coap_option_enum_name_generate(option_number, option_name, typedef_enum_name)
        comment_line = '; '.join(filter(None, [f"{option_name}",  f'Ref: {reference}']))
        enum_list[int(option_number)] = {"enum_name": enum_name, "comment": comment_line}

    return enum_list

def iana_coap_option_c_typedef_enum_update(header_file_content: str) -> str:
    typedef_enum_name = iana_coap_option_settings["name"]
    source_name = iana_coap_option_settings["title"]
    source_url = iana_coap_option_settings["source"]
    csv_file_url = iana_coap_option_settings["csv_url"]

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)
    enum_list = iana_coap_option_parse_csv(read_or_download_csv(csv_file_url, cache_file_path), typedef_enum_name)

    c_range_marker = [
        {"start":0, "end":255, "description":"IETF Review or IESG Approval"},
        {"start":256, "end":2047, "description":"Specification Required"},
        {"start":2048, "end":64999, "description":"Expert Review"},
        {"start":65000, "end":65535, "description":"Experimental use (no operational use)"},
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_head_comment, enum_list, c_range_marker)


###############################################################################
# Content Format Generation
def iana_coap_content_formats_c_enum_name_generate(content_type: str, content_coding: str, typedef_enum_name: str):
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
    # Convert '+' into '_PLUS_' as it
    content_type = re.sub(r'\+', r'_PLUS_', content_type)
    # Convert non alphanumeric characters into variable name friendly underscore
    content_type = re.sub(r'[^a-zA-Z0-9_]', '_', content_type)
    content_type = content_type.strip('_')
    content_type = content_type.upper()
    return f"{typedef_enum_name.upper()}_{content_type}"

def iana_coap_content_formats_parse_csv(csv_content: str, typedef_enum_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    enum_list = {}
    for row in csv_reader:
        content_type = row["Content Type"]
        content_coding = row["Content Coding"]
        id_value = row["ID"]
        reference = row["Reference"]
        if content_type.lower() == "content type": # Skip first header
            continue
        if not content_type or not id_value or content_type.lower() == "unassigned" or "reserve" in content_type.lower():
            continue
        if "-" in id_value:
            continue

        # Add to enum list
        enum_name = iana_coap_content_formats_c_enum_name_generate(content_type, content_coding, typedef_enum_name)
        comment = '; '.join(filter(None, [content_type, content_coding, f'Ref: {reference}']))
        enum_list[int(id_value)] = {"enum_name": enum_name, "comment": comment}
    return enum_list

def iana_coap_content_formats_c_typedef_enum_update(header_file_content: str) -> str:
    source_name = iana_coap_content_format_settings["title"]
    source_url = iana_coap_content_format_settings["source"]
    typedef_enum_name = iana_coap_content_format_settings["name"]

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    # Generate head comment
    c_head_comment = spacing_string + f"/* Autogenerated {source_name} (Source: {source_url}) */\n"

    # Load latest IANA registrations
    csv_file_url = iana_coap_content_format_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    enum_list = iana_coap_content_formats_parse_csv(csv_content, typedef_enum_name)

    # Generate enumeration header content
    c_range_marker = [
        {"start":0, "end":255, "description":"Expert Review"},
        {"start":256, "end":9999, "description":"IETF Review or IESG Approval"},
        {"start":10000, "end":64999, "description":"First Come First Served"},
        {"start":65000, "end":65535, "description":"Experimental use (no operational use)"},
        ]
    return update_c_typedef_enum(header_file_content, c_typedef_name, c_head_comment, enum_list, c_range_marker)


###############################################################################
# Content Format Generation
def iana_coap_signaling_option_number_c_enum_name_generate(coap_code: str, name_value: str, typedef_enum_name: str):
    """
    This generates a c enum name based on coap content type and content coding value
    """
    # Do not include comments indicated by messages within `(...)`
    name_value = re.sub(r'\s+\(.*\)', '', name_value)
    # Convert '+' into '_PLUS_' as it
    name_value = re.sub(r'\+', r'_PLUS_', name_value)
    # Convert non alphanumeric characters into variable name friendly underscore
    coap_code_cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', coap_code).strip('_').upper()
    name_value_cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', name_value).strip('_').upper()
    return f"COAP_CODE_{coap_code_cleaned}_{typedef_enum_name.upper()}_{name_value_cleaned}"

def iana_coap_signaling_option_number_parse_csv(csv_content: str, typedef_enum_name: str):
    """
    Parse and process IANA registration into enums
    """
    csv_lines = csv_content.strip().split('\n')
    csv_reader = csv.DictReader(csv_lines)
    signaling_option_number_format_list = {}
    for row in csv_reader:
        code_application = row["Applies to"]
        id_value = row["Number"]
        name_value = row["Name"]
        reference = row["Reference"]
        if not code_application or not id_value or "unassigned" in name_value.lower() or "reserve" in name_value.lower():
            continue
        if "all" in code_application or "7.xx" in code_application: 
            # Will process later
            continue
        for coap_code in code_application.split(","):
            coap_code = coap_code.strip()
            if coap_code not in signaling_option_number_format_list:
                signaling_option_number_format_list[coap_code] = {} #???
            enum_name = iana_coap_signaling_option_number_c_enum_name_generate(coap_code, name_value, typedef_enum_name)
            # Render C header entry
            c_comment_line = '; '.join(filter(None, [name_value, f'Ref: {reference}']))
            # Add to enum list
            signaling_option_number_format_list[coap_code][int(id_value)] = {"enum_name": enum_name, "comment": c_comment_line}

    for coap_code, signaling_option_number_entry in signaling_option_number_format_list.items():
        csv_lines = csv_content.strip().split('\n')
        csv_reader = csv.DictReader(csv_lines)
        for row in csv_reader: 
            code_application = row["Applies to"]
            id_value = row["Number"]
            name_value = row["Name"]
            reference = row["Reference"]
            if "all" in code_application or "7.xx" in code_application:
                if coap_code not in signaling_option_number_format_list:
                    signaling_option_number_format_list[coap_code] = {} #???
                enum_name = iana_coap_signaling_option_number_c_enum_name_generate(coap_code, name_value, typedef_enum_name)
                # Render C header entry
                c_comment_line = '; '.join(filter(None, [name_value, f'Ref: {reference}']))
                # Add to enum list
                signaling_option_number_format_list[coap_code][int(id_value)] = {"enum_name": enum_name, "comment": c_comment_line}

    return signaling_option_number_format_list

def iana_coap_signaling_option_number_c_typedef_enum_update(header_file_content: str) -> str:
    source_name = iana_coap_signaling_option_numbers_settings["title"]
    source_url = iana_coap_signaling_option_numbers_settings["source"]
    typedef_enum_name = iana_coap_signaling_option_numbers_settings["name"]
    csv_file_url = iana_coap_signaling_option_numbers_settings["csv_url"]
    cache_file_path = iana_cache_dir_path + os.path.basename(csv_file_url)

    # Generate typedef name
    c_typedef_name = f"{typedef_enum_name}_t"

    # Load latest IANA registrations
    csv_content = read_or_download_csv(csv_file_url, cache_file_path)

    # Parse and process IANA registration into enums
    signaling_option_number_format_list = iana_coap_signaling_option_number_parse_csv(csv_content, typedef_enum_name)

    for coap_code, enum_list in signaling_option_number_format_list.items():
        # Generate typedef enum name
        coap_code_var_name = re.sub(r'[^a-zA-Z0-9_]', '_', coap_code)
        typedef_enum_name = f"coap_code_{coap_code_var_name}_{c_typedef_name}"

        # Generate head comment
        c_head_comment = spacing_string + f"/* Autogenerated {source_name} for {coap_code} (Source: {source_url}) */\n"

        # Generate enumeration header content
        header_file_content = update_c_typedef_enum(header_file_content, typedef_enum_name, c_head_comment, enum_list)

    return header_file_content

###############################################################################
# Create Header

def iana_coap_c_header_update(header_filepath: str):
    # If file doesn't exist yet then write a new file
    os.makedirs(os.path.dirname(header_filepath), exist_ok=True)
    if not os.path.exists(header_filepath):
        with open(header_filepath, 'w+') as file:
            file.write(default_cbor_header_c)

    # Get latest header content
    with open(header_filepath, 'r') as file:
        header_file_content = file.read()

    # Resync All Values
    header_file_content = iana_coap_request_response_c_typedef_enum_update(header_file_content)
    header_file_content = iana_coap_option_c_typedef_enum_update(header_file_content)
    header_file_content = iana_coap_content_formats_c_typedef_enum_update(header_file_content)
    header_file_content = iana_coap_signaling_option_number_c_typedef_enum_update(header_file_content)

    # Write new header content
    with open(header_filepath, 'w') as file:
        file.write(header_file_content)

    # Indicate header has been synced
    print(f"C header file '{header_filepath}' updated successfully.")

def main():
    iana_coap_c_header_update(iana_coap_c_header_file_path)

if __name__ == "__main__":
    main()
