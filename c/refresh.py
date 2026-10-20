#!/usr/bin/env python3
"""
refresh.py — one IANA update, independent of any CI service: sync, name, and a review summary.

1. Keep a copy of db/ as it is now (the summary compares against it; git is not needed).
2. `sync.py` into a new dated snapshot directory, then `name.py`.
3. If db/ did not change, delete the snapshot and write no summary.
   Otherwise write a Markdown summary: what needs a decision, the new names, and sync warnings.

The GitHub workflow (.github/workflows/iana-sync.yml) only adds scheduling and opening a pull request
around this script; a cron job or another CI system can run `make refresh` the same way.
Exits 0 whether or not anything changed (the summary file only exists when something did),
and 1 if the sync itself failed.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import check
import recfile
import report

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)
db_dir = os.path.join(repo_dir, 'db')
snapshot_root = os.path.join(repo_dir, 'iana', 'snapshots')


class RefreshError(Exception):
    pass


def run_script(script, *args):
    """Run one of the c/*.py tools, echoing its output as it arrives; return (exit code, output)."""
    process = subprocess.Popen([sys.executable, script, *args], cwd=script_dir, text=True, encoding='utf-8',
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = []
    for line in process.stdout:
        sys.stdout.write(line)
        lines.append(line)
    return process.wait(), ''.join(lines)


def read_db(directory):
    contents = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith('.rec'):
            with open(os.path.join(directory, name), encoding='utf-8') as f:
                contents[name] = f.read()
    return contents


def free_snapshot_dir(root, date):
    """iana/snapshots/<date>, or <date>-2, -3, ... when a snapshot was already taken that day."""
    path, run = os.path.join(root, date), 2
    while os.path.exists(path):
        path, run = os.path.join(root, f'{date}-{run}'), run + 1
    return path


def refresh(directory=db_dir, snapshots=snapshot_root, date=None, intro='', run=run_script):
    """Return (summary Markdown, snapshot dir), or (None, None) when IANA brought nothing new."""
    date = date or datetime.now(timezone.utc).date().isoformat()
    before = read_db(directory)
    snapshot = free_snapshot_dir(snapshots, date)

    code, sync_output = run('sync.py', '--snapshot-dir', snapshot)
    if code != 0:
        raise RefreshError(f'sync.py failed (exit {code}); db/ may be partly updated, review it with `git diff db`')
    code, name_output = run('name.py')
    if code != 0 and 'Traceback' in name_output:  # exit 1 without a traceback = entries left for a human
        raise RefreshError('name.py crashed')

    after = read_db(directory)
    if after == before:
        shutil.rmtree(snapshot, ignore_errors=True)
        return None, None

    db_files = [os.path.join(directory, name) for name in after]
    sections, breaking = report.compare(lambda name: recfile.parse(before.get(name, '')), db_files)
    errors = [error for db_file in db_files for error in check.check_file(db_file)]
    check_status = 'passes' if not errors else f'fails until the decisions below are made ({len(errors)} errors)'

    lines = [intro, ''] if intro else []
    lines += [
        f'IANA sync {date}. Source snapshot: `{os.path.relpath(snapshot, repo_dir)}/`. `make check` {check_status}.',
        '',
        '**To finish:** read the names below (they cannot change once published). Fix a name by editing its '
        '`Words` and setting `Source: manual`, or run `make review`. Merge once `make ci BASE=<target branch>` '
        'passes.',
        '',
        report.render('the previous `db/`', sections, breaking),
    ]
    if 'REVIEW NEEDED' in sync_output:
        warnings = sync_output[sync_output.index('REVIEW NEEDED'):].split('\n\nRun `make name`')[0].rstrip()
        lines += ['', '<details><summary>Sync warnings</summary>', '', '```', warnings, '```', '', '</details>']
    return '\n'.join(lines) + '\n', snapshot


def main():
    parser = argparse.ArgumentParser(description='Sync IANA, name new entries, and summarise the changes for review')
    parser.add_argument('--summary', help='write the Markdown summary here (default: print it); '
                                          'the file is removed when nothing changed')
    parser.add_argument('--intro', default='', help='a line to put first in the summary, e.g. a link to the CI run')
    args = parser.parse_args()

    try:
        summary, snapshot = refresh(intro=args.intro)
    except RefreshError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)

    if summary is None:
        if args.summary and os.path.exists(args.summary):
            os.remove(args.summary)
        print('\nIANA registries match db/: nothing to review (snapshot discarded).')
        return
    if args.summary:
        with open(args.summary, 'w', encoding='utf-8') as f:
            f.write(summary)
        print(f'\ndb/ changed. Snapshot: {os.path.relpath(snapshot, repo_dir)}/. Summary: {args.summary}')
    else:
        print('\n' + summary)
    print('Next: `make review` for open decisions, then commit db/ and the snapshot.')


if __name__ == '__main__':
    main()
