#!/usr/bin/env python3
"""Validate the staff nginx mounts in resolved library Compose JSON."""
import argparse
import json
from pathlib import Path
import sys


def validate(config, library_dir):
    volumes = config.get('services', {}).get('app', {}).get('volumes', [])
    for name in ('libstaff.conf', 'block-catalog-client.conf'):
        source = library_dir / 'docker' / name
        if name != 'libstaff.conf' and not source.exists():
            continue
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f'Missing nginx configuration: docker/{name}')
        target = '/etc/nginx/conf.d/' + name
        mount = next((v for v in volumes if isinstance(v, dict) and v.get('target') == target), None)
        if not mount or mount.get('type') != 'bind' or mount.get('read_only') is not True:
            raise ValueError(f'library app requires a read-only mount: ./docker/{name}:{target}:ro')
        if Path(mount.get('source', '')).resolve() != source.resolve():
            raise ValueError(f'Unexpected source of nginx mount: {target}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.load(sys.stdin)
        if not isinstance(config, dict):
            raise ValueError('Expected resolved Compose JSON')
        validate(config, args.library.resolve())
    except (ValueError, OSError) as exc:
        # Never dump Compose JSON: it includes environment secrets.
        print(f'Staff proxy preflight failed: {exc}', file=sys.stderr)
        return 1
    print('Staff proxy mounts: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
