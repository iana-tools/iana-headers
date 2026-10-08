"""Recognize explicit provisional/temporary IANA registration markers."""

import re


LIFECYCLE_VALUES = {'provisional', 'temporary', 'under-review', 'stable'}
REVIEW_VALUES = {'monitor', 'pending', 'resolved'}

_TEMPORARY_RE = re.compile(r'\(\s*temporary(?:\s*[-:)]|\s+registered\b)', re.IGNORECASE)
_PROVISIONAL_RE = re.compile(r'(?:^|[;,])\s*provisional\s*$', re.IGNORECASE)
_UNDER_REVIEW_RE = re.compile(r'\bunder\s+review\b', re.IGNORECASE)


def from_semantics(semantics):
    """Return a lifecycle marker only for explicit registration-status wording.

    Avoids false positives such as the ordinary HTTP phrase "Temporary Redirect".
    """
    text = semantics.strip()
    if _TEMPORARY_RE.search(text):
        return 'temporary'
    if _PROVISIONAL_RE.search(text):
        return 'provisional'
    if _UNDER_REVIEW_RE.search(text):
        return 'under-review'
    return ''
