"""Read-only acquisition of an immutable Release pair; never rebuild or publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

import native_pack as native
import release
import serverpack

REPOSITORY = 'aiagate/okd-server-modpack'
SHA = re.compile(r'[0-9a-f]{40}')
LIMIT = 2 * 1024 * 1024


def gh_api(path, binary=False):
    args = ['gh', 'api', f'repos/{REPOSITORY}/{path}']
    if binary:
        args += ['-H', 'Accept: application/octet-stream']
    try:
        return subprocess.check_output(args, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        raise release.Invalid('published Release read failed; no rebuild or retry fallback') from None


def git(*args):
    try:
        return subprocess.check_output(['git', *args], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        raise release.Invalid('recorded source commit is unavailable or not an ancestor of this checkout') from None


def source_inputs(commit):
    release.need(isinstance(commit, str) and SHA.fullmatch(commit), 'invalid source commit')
    git('merge-base', '--is-ancestor', commit, 'HEAD')
    # Read only the bounded public pack tree. Never execute source-commit scripts.
    entries = git('ls-tree', '-rz', commit, '--', 'pack').split(b'\0')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        total = 0
        for entry in entries:
            if not entry:
                continue
            header, raw_name = entry.split(b'\t', 1)
            mode, kind, oid = header.split()
            name = raw_name.decode('utf-8')
            path = PurePosixPath(name)
            release.need(mode == b'100644' and kind == b'blob' and path.parts[0] == 'pack' and
                         not path.is_absolute() and '..' not in path.parts,
                         'source pack must contain only regular safe files')
            blob = git('cat-file', 'blob', oid.decode())
            total += len(blob)
            release.need(len(blob) <= LIMIT and total <= 32 * 1024 * 1024, 'source pack exceeds bounds')
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
        return native.load_inputs(root / 'pack')


def validate_receipt(record, client, client_record, server, server_record, *, published=False):
    current = native.load_inputs()
    meta = current[0]
    tag = 'v' + meta['version']
    release.need(isinstance(record, dict) and record.get('schema_version') == 1 and
                 record.get('repository') == REPOSITORY and record.get('tag') == tag,
                 'Release receipt repository/version mismatch')
    source = source_inputs(record.get('source_commit'))
    # A changed target/version/MOD/settings needs a new reviewed release. No rebinding.
    release.need(source == current, 'current pack differs from recorded release source; use a new version')
    release.need(record.get('source_sha256') == source[3] and record.get('client') == client_record and
                 record.get('server') == server_record,
                 'Release receipt differs from source or ZIP receipts')
    native.verify_client(client, client_record, source)
    serverpack.verify_prepared(server, server_record, client, native.policy(source[2]), meta['version'], source[1])
    if published:
        row = release.parse_json(gh_api('releases/tags/' + tag))
        ref = release.parse_json(gh_api('git/ref/tags/' + tag))
        release.need(row.get('tag_name') == tag and row.get('draft') is False and row.get('published_at') and
                     ref.get('ref') == 'refs/tags/' + tag and ref.get('object', {}).get('type') == 'commit' and
                     ref['object']['sha'] == record['source_commit'], 'published tag/source commit mismatch')
        for path in (client, server):
            asset = asset_by_name(row, path.name)
            release.need(asset['size'] == path.stat().st_size and
                         asset['digest'] == 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(),
                         'published ZIP differs from approved artifacts')
        # Bind receipt itself to the immutable published bytes, too.
        asset = asset_by_name(row, 'github-release-receipt.json')
        raw = download_asset(asset, LIMIT)
        release.need(release.parse_json(raw) == record, 'published provenance receipt changed')
    else:
        release.need(record['source_commit'] == git('rev-parse', 'HEAD').decode().strip(),
                     'new build receipt belongs to another checkout')
    return source


def asset_by_name(row, name):
    assets = row.get('assets')
    release.need(isinstance(assets, list), 'Release assets shape changed')
    found = [a for a in assets if isinstance(a, dict) and a.get('name') == name]
    release.need(len(found) == 1, 'required Release asset missing or ambiguous; never rebuild as fallback')
    asset = found[0]
    release.need(release.positive(asset.get('id')) and release.positive(asset.get('size')) and
                 isinstance(asset.get('digest'), str) and re.fullmatch(r'sha256:[0-9a-f]{64}', asset['digest']),
                 'Release asset identity/digest missing')
    return asset


def download_asset(asset, limit):
    release.need(asset['size'] <= limit, 'Release asset exceeds limit')
    blob = gh_api(f'releases/assets/{asset["id"]}', binary=True)
    release.need(len(blob) == asset['size'] and asset['digest'] == 'sha256:' + hashlib.sha256(blob).hexdigest(),
                 'downloaded Release asset digest/size mismatch')
    return blob


def acquire(output):
    meta = native.load_inputs()[0]
    tag = 'v' + meta['version']
    release.need(not output.exists(), 'use new acquisition directory')
    row = release.parse_json(gh_api('releases/tags/' + tag))
    release.need(row.get('tag_name') == tag and row.get('draft') is False and row.get('published_at'),
                 'select an existing published release; no rebuild fallback')
    names = ['github-release-receipt.json', 'client.json', 'server.json',
             f'okd-server-modpack-{meta["version"]}.zip', f'okd-server-modpack-{meta["version"]}-serverpack.zip']
    output.mkdir(parents=True)
    for name in names:
        blob = download_asset(asset_by_name(row, name), release.MAX_ZIP if name.endswith('.zip') else LIMIT)
        (output / name).write_bytes(blob)
    record = release.parse_json((output / names[0]).read_bytes())
    c = release.parse_json((output / 'client.json').read_bytes())
    s = release.parse_json((output / 'server.json').read_bytes())
    validate_receipt(record, output / names[3], c, output / names[4], s, published=True)
    # Separate acquisition evidence; immutable original provenance is preserved verbatim.
    (output / 'acquisition.json').write_text(json.dumps(dict(schema_version=1, repository=REPOSITORY,
        tag=tag, release_id=row['id'], source_commit=record['source_commit'],
        assets=[{k: asset_by_name(row, name)[k] for k in ('id', 'name', 'size', 'digest')} for name in names],
        rebuilt=False), indent=2) + '\n')
    return output / names[3]


def record_build(output):
    inputs = native.load_inputs()
    c = release.parse_json((output / 'client.json').read_bytes())
    s = release.parse_json((output / 'server.json').read_bytes())
    record = dict(schema_version=1, repository=REPOSITORY, tag='v' + inputs[0]['version'],
                  source_commit=git('rev-parse', 'HEAD').decode().strip(), source_sha256=inputs[3],
                  client=c, server=s, runtime_verified=False)
    release.need(os.environ.get('GITHUB_SHA', record['source_commit']) == record['source_commit'],
                 'build checkout differs from workflow commit')
    validate_receipt(record, output / c['filename'], c, output / s['filename'], s)
    with (output / 'github-release-receipt.json').open('x') as handle:
        json.dump(record, handle, indent=2)
        handle.write('\n')


def require_new_version():
    tag = 'v' + native.load_inputs()[0]['version']
    response = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/releases/tags/{tag}'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    release.need(response.returncode != 0 and b'HTTP 404' in response.stderr,
                 'new build requires a version without a published Release; reuse published bytes')
    gh_api('releases?per_page=1') # Prove read permission/connectivity, not a transport failure.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--record-build', action='store_true')
    parser.add_argument('--require-new-version', action='store_true')
    args = parser.parse_args()
    if not args.require_new_version and args.output is None:
        parser.error('--output is required for acquisition/build provenance')
    try:
        if args.require_new_version:
            require_new_version()
        elif args.record_build:
            record_build(args.output)
        else:
            acquire(args.output)
        print('Exact Release bytes/source verified; no rebuild or publication performed.')
    except (release.Invalid, OSError, ValueError, KeyError, TypeError):
        print('STOP: Release acquisition/provenance failed; no rebuild fallback or publication.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
