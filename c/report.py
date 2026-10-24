#!/usr/bin/env python3
"""
report.py — Markdown summary of what changed in db/ since a git ref (or a copy of db/), for review.

Lists what still needs a decision, new names with the C identifier each produces, lifecycle
changes, skips, and renames or removals of names that were already published. With --strict
it exits non-zero on an unexplained rename/removal of a stable published name: a published
identifier must not change unless the record documents it with `Previous Words: <old words>`.
"""

import argparse
import os
import subprocess
import sys

import name
import recfile
import registry

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')

UNNAMED_SOURCES = ('new', 'needs-manual')
NOT_PERMANENT = ('temporary', 'provisional', 'under-review')
FOLD_ROWS = 20


def _key(fname, tag):
    try:
        return registry.parse_tag(fname, tag)
    except (ValueError, KeyError):
        return tag.strip()


def _by_key(fname, records):
    return {_key(fname, r.get('Tag', '')): r for r in records if r.get('Tag', '').strip()}


def _base_records(ref, fname):
    """Records of db/<fname> at a git ref; [] if the file did not exist there."""
    result = subprocess.run(['git', 'show', f'{ref}:db/{fname}'], cwd=repo_dir,
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        if 'does not exist' in result.stderr or 'exists on disk, but not in' in result.stderr:
            return []
        raise RuntimeError(f'git show {ref}:db/{fname} failed: {result.stderr.strip()}')
    return recfile.parse(result.stdout)


def _cell(text, limit=140):
    text = ' '.join((text or '').split()).replace('|', '\\|')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _published(rec):
    """A name that is in the generated headers today."""
    return bool(rec.get('Words', '').strip()) and rec.get('Source', '').strip() not in UNNAMED_SOURCES + ('skip',)


def _identifier(fname, words):
    return f"`{name._enum_prefix(fname)}{'_'.join(words.split()).upper()}`"


def _why_unnamed(rec):
    suggested = rec.get('Suggested Words', '').strip()
    if rec.get('Source', '').strip() == 'new':
        return 'not named yet (`make name`)'
    if not suggested or suggested == name.NO_SUGGESTION:
        return 'no usable suggestion'
    if name.too_long(suggested):
        return f'suggestion too long for a name ({len(suggested.split())} words)'
    return f'suggestion `{_cell(suggested, 60)}` collides with another name'


def _how_named(rec):
    source = rec.get('Source', '').strip()
    suggested = rec.get('Suggested Words', '').strip()
    by = rec.get('Suggested By', '').strip() or 'heuristic'
    words = rec.get('Words', '').strip()
    if source in ('heuristic', 'llm'):
        return f'{source}, not reviewed yet'
    if suggested and suggested == words:
        return f'{by} suggestion accepted'
    if suggested and suggested != name.NO_SUGGESTION:
        return f'edited (suggested: {suggested})'
    return 'manual'


def git_base_reader(ref):
    return lambda fname: _base_records(ref, fname)


def dir_base_reader(directory):
    """Compare against a plain directory of .rec files (no git needed), e.g. an unpacked release."""
    return lambda fname: recfile.read(os.path.join(directory, fname))


def compare(read_base, db_files):
    """Return (sections, breaking): Markdown table rows per section, and the unexplained breaking changes.

    read_base(fname) returns the records of db/<fname> before the change.
    """
    sections = {key: [] for key in ('decide', 'breaking', 'renamed', 'new', 'lifecycle', 'skipped', 'wording')}
    breaking = []
    for db_file in db_files:
        fname = os.path.basename(db_file)
        base = _by_key(fname, read_base(fname))
        head = _by_key(fname, recfile.read(db_file))

        for key, rec in head.items():
            tag = rec['Tag'].strip()
            old = base.get(key)
            words = rec.get('Words', '').strip()
            source = rec.get('Source', '').strip()
            semantics = rec.get('Semantics', '')

            if source in UNNAMED_SOURCES:
                sections['decide'].append(f'| {fname} | {tag} | {_why_unnamed(rec)} | {_cell(semantics)} |')
            if rec.get('Review', '').strip() == 'pending':
                sections['decide'].append(
                    f"| {fname} | {tag} | IANA changed this {rec.get('Lifecycle', '').strip() or 'tracked'} "
                    f"registration: `{_cell(rec.get('IANA Semantics', ''), 100)}` | {_cell(semantics)} |")

            if old is not None and _published(old):
                old_words = old.get('Words', '').strip()
                if source == 'skip' or not words:
                    line = f'| {fname} | {tag} | {_identifier(fname, old_words)} | removed ({source}) | {_cell(rec.get("Note", ""))} |'
                    if old.get('Lifecycle', '').strip() in NOT_PERMANENT or rec.get('Note', '').strip():
                        sections['renamed'].append(line)
                    else:
                        sections['breaking'].append(line)
                        breaking.append(f'{fname} Tag {tag}')
                elif words != old_words:
                    line = (f'| {fname} | {tag} | {_identifier(fname, old_words)} | '
                            f'{_identifier(fname, words)} | {_cell(semantics)} |')
                    if (old.get('Lifecycle', '').strip() in NOT_PERMANENT
                            or rec.get('Previous Words', '').strip() == old_words):
                        sections['renamed'].append(line)
                    else:
                        sections['breaking'].append(line)
                        breaking.append(f'{fname} Tag {tag}')
            elif words and source not in UNNAMED_SOURCES + ('skip',):
                sections['new'].append(
                    f'| {fname} | {tag} | {_identifier(fname, words)} | {_how_named(rec)} | {_cell(semantics)} |')

            newly_skipped = source == 'skip' and (old is None or old.get('Source', '').strip() in UNNAMED_SOURCES)
            if newly_skipped:
                sections['skipped'].append(f'| {fname} | {tag} | {_cell(rec.get("Note", ""))} | {_cell(semantics)} |')

            iana_now = rec.get('IANA Semantics', '').strip()
            if (old is not None and iana_now and rec.get('Review', '').strip() != 'pending'
                    and iana_now != old.get('IANA Semantics', '').strip()):
                sections['wording'].append(f'| {fname} | {tag} | {_cell(semantics, 90)} | {_cell(iana_now, 90)} |')

            if old is not None:
                before = (old.get('Lifecycle', '').strip(), old.get('Review', '').strip())
                after = (rec.get('Lifecycle', '').strip(), rec.get('Review', '').strip())
                if before != after and after[1] != 'pending':
                    sections['lifecycle'].append(
                        f"| {fname} | {tag} | {'/'.join(filter(None, before)) or '—'} → "
                        f"{'/'.join(filter(None, after)) or '—'} | {_cell(semantics)} |")

        for key, old in base.items():
            if key not in head and _published(old):
                sections['breaking'].append(
                    f"| {fname} | {old['Tag'].strip()} | {_identifier(fname, old['Words'].strip())} | "
                    f"record deleted | |")
                breaking.append(f"{fname} Tag {old['Tag'].strip()}")
    return sections, breaking


def render(base_label, sections, breaking):
    """base_label is Markdown naming what was compared against, e.g. '`origin/main`'."""
    counts = {key: len(lines) for key, lines in sections.items()}
    out = [f'## IANA db changes since {base_label}', '']
    if not any(counts.values()):
        return '\n'.join(out + ['No changes to names, lifecycle states or skips.', ''])

    summary = []
    if counts['decide']:
        summary.append(f"**{counts['decide']} need a decision** (`make review`)")
    if breaking:
        summary.append(f'**{len(breaking)} break a published name**')
    for key, label in (('new', 'new names'), ('renamed', 'expected renames/removals'),
                       ('lifecycle', 'lifecycle updates'), ('skipped', 'skipped'),
                       ('wording', 'IANA wording changes')):
        if counts[key]:
            summary.append(f'{counts[key]} {label}')
    out += [' · '.join(summary), '']

    def table(title, header, key, intro=''):
        if not sections[key]:
            return
        out.extend([f'### {title}', ''])
        if intro:
            out.extend([intro, ''])
        rows = [header, '|' + ' --- |' * (header.count(' | ') + 1)] + sections[key]
        if len(sections[key]) > FOLD_ROWS:  # keep a long table from burying the rest of a PR description
            rows = [f'<details><summary>{len(sections[key])} rows</summary>', ''] + rows + ['', '</details>']
        out.extend(rows)
        out.append('')

    table('Needs a decision', '| File | Tag | Why | IANA Semantics |', 'decide',
          '`make check` blocks generation until these are resolved. Run `make review`, or edit `db/*.rec` '
          'directly (set `Source: manual` on a name you choose).')
    table('Breaking: published name changed', '| File | Tag | Was | Now | IANA Semantics |', 'breaking',
          'These identifiers are already in the published headers. Revert the change, or document an intended '
          'rename with `Previous Words: <old words>` on the record (or a `Note` for a removal).')
    table('New names', '| File | Tag | C identifier | How named | IANA Semantics |', 'new',
          'Check each name reads well: it cannot change once published. To change one in this pull request, '
          'edit `Words` and set `Source: manual`.')
    table('Expected renames and removals', '| File | Tag | Was | Now | Detail |', 'renamed',
          'Not-yet-permanent registrations, or renames documented with `Previous Words`.')
    table('Lifecycle updates', '| File | Tag | Lifecycle/Review | IANA Semantics |', 'lifecycle')
    table('Skipped (not in the headers)', '| File | Tag | Reason | IANA Semantics |', 'skipped')
    table('IANA wording changed (informational)', '| File | Tag | db Semantics | IANA now says |', 'wording',
          'Names stay as published. To make the header comment follow IANA, copy the text into `Semantics` '
          'and delete `IANA Semantics`.')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='Summarise db/ changes since a git ref (or a db/ copy) as Markdown')
    base = parser.add_mutually_exclusive_group()
    base.add_argument('--base', default='HEAD', help='git ref to compare against (default: HEAD)')
    base.add_argument('--base-dir', help='directory of .rec files to compare against instead of a git ref')
    parser.add_argument('--strict', action='store_true',
                        help='exit 1 if a published stable name is renamed or removed without documentation')
    parser.add_argument('--output', help='write the Markdown here instead of stdout')
    args = parser.parse_args()

    db_files = [os.path.join(db_dir, f) for f in sorted(os.listdir(db_dir)) if f.endswith('.rec')]
    try:
        read_base = dir_base_reader(args.base_dir) if args.base_dir else git_base_reader(args.base)
        sections, breaking = compare(read_base, db_files)
    except RuntimeError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(2)
    markdown = render(f'`{args.base_dir or args.base}`', sections, breaking)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(markdown + '\n')
    else:
        print(markdown)
    if args.strict and breaking:
        print(f"ERROR: {len(breaking)} published name(s) changed without `Previous Words`: {', '.join(breaking)}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
