"""Validate free mode prerequisites without calling any language model."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', action='store_true')
    args = parser.parse_args()
    print('Python:', platform.python_version(), '|', sys.executable)
    print('System:', platform.system(), platform.machine())
    if sys.version_info < (3, 10):
        print('FAIL: Python 3.10 or later is required.')
        return 1
    root = Path(__file__).resolve().parent
    try:
        config = json.loads((root / 'config.free.json').read_text('utf-8'))
        assert 1 <= config['max_items'] <= 20
        probe = root / 'outputs' / '.environment-write-check'
        probe.parent.mkdir(exist_ok=True)
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        print('PASS: config and output write access. No pip packages, keys or Codex login needed.')
        if args.network:
            from free_digest import Client, parse_atom
            papers = parse_atom(Client(config).fetch('https://export.arxiv.org/api/query?search_query=cat%3Acs.RO&max_results=1'))
            print('PASS: arXiv API,', len(papers), 'record(s).')
        if os.name != 'nt':
            print('INFO: use cron or GitHub Actions for scheduling; Windows notifications unavailable.')
        return 0
    except Exception as exc:
        print('FAIL:', type(exc).__name__, str(exc))
        print('See ENVIRONMENT.md for installation, network and proxy instructions.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
