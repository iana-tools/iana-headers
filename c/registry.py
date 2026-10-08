"""Registry-specific helpers shared by sync / name / check / generate."""

# RFC 7252 section 3: a CoAP code is "class.detail" (e.g. "2.05") packed as class<<5 | detail.
# The label is part of the published C identifier (COAP_CODE_<LABEL>_<NAME>), so it must not drift.
COAP_CLASS_LABEL = {
    0: 'Method',
    2: 'Success',
    4: 'Client Error',
    5: 'Server Error',
    7: 'Signaling Code',
}


def coap_code_to_int(code):
    """'2.05' -> 69. Raises ValueError on anything that is not 'class.detail'."""
    cls, detail = code.strip().split('.')
    return ((int(cls) & 0x07) << 5) | (int(detail) & 0x1F)


def coap_class_label(code):
    """'4.04' -> 'Client Error'. Raises ValueError/KeyError for classes the registry does not define."""
    return COAP_CLASS_LABEL[int(code.strip().split('.')[0])]


# How each db file's Tag is interpreted. Files not listed here use plain integers.
#   coap_code        'class.detail'          -> packed code
#   signaling_option 'class.detail.number'   -> (packed code, option number)
#   name             free text (HTTP field name); has no numeric value
TAG_KIND = {
    'coap_request_codes.rec': 'coap_code',
    'coap_response_codes.rec': 'coap_code',
    'coap_signaling_codes.rec': 'coap_code',
    'coap_signaling_option_numbers.rec': 'signaling_option',
    'http_field_names.rec': 'name',
}


def parse_tag(db_filename, tag):
    """Return the enum key for a record Tag. Raises ValueError if the Tag is malformed for this registry."""
    tag = tag.strip()
    kind = TAG_KIND.get(db_filename, 'int')
    if kind == 'int':
        return int(tag)
    if kind == 'coap_code':
        return coap_code_to_int(tag)
    if kind == 'signaling_option':
        code, number = tag.rsplit('.', 1)
        return coap_code_to_int(code), int(number)
    if not tag:
        raise ValueError('empty Tag')
    return tag


def words_scope(db_filename, tag):
    """Words only have to be unique inside one generated C enum.

    Signaling option numbers get one enum per CoAP code, so 'oscore' is legitimately
    used for every code. Everything else is a single enum per file ('' scope).
    """
    if TAG_KIND.get(db_filename) == 'signaling_option':
        return tag.strip().rsplit('.', 1)[0]
    return ''
