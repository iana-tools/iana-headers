"""Minimal GNU recfile reader/writer — no external dependencies."""

import os


def read(filepath):
    """Parse a recfile and return a list of record dicts, skipping directives and comments."""
    records = []
    current = {}
    last_key = None
    if not os.path.exists(filepath):
        return records
    with open(filepath, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.rstrip('\n')
            if line.startswith('%') or line.startswith('#'):
                last_key = None
                continue
            if line == '':
                if current:
                    records.append(current)
                    current = {}
                last_key = None
            elif line.startswith('+ ') and last_key:
                current[last_key] = current[last_key] + '\n' + line[2:]
            elif ': ' in line:
                key, _, value = line.partition(': ')
                current[key.strip()] = value
                last_key = key.strip()
            elif line.endswith(':'):
                key = line[:-1].strip()
                current[key] = ''
                last_key = key
    if current:
        records.append(current)
    return records


def append_record(filepath, record):
    """Append a single record dict to a recfile (creates file with header if needed)."""
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write('\n')
        for key, value in record.items():
            f.write(f'{key}: {value}\n')


def write_header(filepath, rec_type, key_field, doc_url):
    """Write the recfile directive header (only if file is new/empty)."""
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f'%rec: {rec_type}\n')
        f.write(f'%key: {key_field}\n')
        f.write(f'%doc: {doc_url}\n')
