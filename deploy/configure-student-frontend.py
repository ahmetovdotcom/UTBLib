#!/usr/bin/env python3
"""Configure the two existing deployments; never print or replace a working key."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import secrets
import shutil
import tempfile


def values(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r'\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        if match:
            value = match[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[match[1]] = value
    return result


def patched(text, changes):
    lines = text.splitlines()
    for key, value in changes.items():
        pattern = re.compile(r'^\s*' + re.escape(key) + '=')
        lines = [line for line in lines if not pattern.match(line)]
        lines.append(key + '=' + value)
    return '\n'.join(lines) + '\n'


def plan(utb_text, library_text):
    utb, library = values(utb_text), values(library_text)
    keys = {v for v in (utb.get('STUDENT_BRIDGE_KEY'), library.get('STUDENT_BRIDGE_KEY')) if v}
    if len(keys) > 1:
        raise ValueError('STUDENT_BRIDGE_KEY differs between projects; refusing to rotate it implicitly')
    key = next(iter(keys), secrets.token_hex(32))
    # Keep keys portable across dotenv, Compose and PHP without quoting/interpolation.
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', key):
        raise ValueError('Existing bridge key has an unsupported format; no files changed')
    required = ['AD_HOST', 'AD_BIND_DN', 'AD_BIND_PASSWORD', 'AD_BASE_DN', 'AD_CA_CERT_PATH', 'APP_KEY']
    if any(not library.get(k) for k in required):
        raise ValueError('Missing existing library configuration: ' + ', '.join(k for k in required if not library.get(k)))
    if not library.get('APP_URL', '').startswith('https://'):
        raise ValueError('Production APP_URL must already use HTTPS')
    library_changes = dict(STUDENT_BRIDGE_KEY=key, UTBLIB_FRONTEND_ONLY='true',
        UTBLIB_CATALOG_ENABLED='true', UTBLIB_CONTENT_ENABLED='true',
        UTBLIB_CATALOG_URL='http://utblib-web', UTBLIB_CATALOG_TIMEOUT='10',
        APP_ENV='production', APP_DEBUG='false', APP_LIVE_SYNC='false',
        APP_DEMO_LOGIN_ENABLED='false', BREAK_GLASS_LOGIN_ENABLED='false',
        AD_ENABLED='true', AD_USE_SSL='true', AD_REQUIRE_CERT='true',
        SESSION_SECURE_COOKIE='true')
    return patched(utb_text, {'STUDENT_BRIDGE_KEY': key}), patched(library_text, library_changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Write config; default only validates')
    args = parser.parse_args()
    paths = [Path(__file__).resolve().parents[1] / '.env.server', args.library.resolve() / '.env']
    originals = [path.read_text() for path in paths]
    outputs = plan(*originals)
    if not args.apply:
        print('Configuration validated. Run with --apply to save both files.')
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(3)
    # Back up BOTH before touching either; keep private backups outside build contexts.
    for path in paths:
        backup_dir = path.parent.parent / 'frontend-deploy-backups' / stamp / path.parent.name
        backup_dir.mkdir(parents=True, mode=0o700)
        backup = backup_dir / path.name
        shutil.copyfile(path, backup)
        backup.chmod(0o600)
        print('Config backup:', backup)
    for path, output in zip(paths, outputs):
        if path.read_text() == output:
            continue
        stat = path.stat()
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.frontend-env-')
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temporary, stat.st_uid, stat.st_gid)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print('Both configurations saved. Secrets were not printed. Recreate the containers next.')


if __name__ == '__main__':
    main()
