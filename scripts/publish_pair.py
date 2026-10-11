"""Publish verified client/server bytes once, with durable per-file claims.

Default: offline dry-run. An ambiguous API response never triggers an automatic retry.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import uuid
import zipfile
from urllib.parse import quote

import release
import serverpack

REPOSITORY = 'aiagate/okd-server-modpack'


def fingerprint(project, version, client_sha, server_sha):
    return dict(project_id=project, version=version, client_sha256=client_sha,
                server_sha256=server_sha)


def check_record(record, identity, kind, parent=None):
    release.need(isinstance(record, dict) and record.get('schema_version') == 1 and
                 all(record.get(k) == v for k, v in identity.items()) and
                 record.get('kind') == kind and release.positive(record.get('file_id')),
                 'publication result does not match the verified bytes/project/version')
    if kind == 'server':
        release.need(record.get('parent_file_id') == parent, 'server result has a different parent')
    return record['file_id']


class GitHubJournal:
    """Immutable Release assets: claim BEFORE POST, result AFTER accepted ID.

    A claim without a result blocks every later run, including a fresh dispatch.
    No clobber/delete. Artifacts are supplementary evidence, not the durable lock.
    """
    def __init__(self, tag, identity):
        self.tag, self.identity = tag, identity

    def command(self, args, *, output=False):
        try:
            return subprocess.check_output(['gh', *args], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            raise release.Invalid('GitHub journal operation failed; no automatic retry') from None

    def name(self, kind, phase):
        return f'curseforge-{kind}-{self.identity[kind + "_sha256"]}-{phase}.json'

    def read(self, kind, phase):
        assets = release.parse_json(self.command(['release', 'view', self.tag, '--repo',
            REPOSITORY, '--json', 'assets']))['assets']
        matches = [a for a in assets if a['name'] == self.name(kind, phase)]
        release.need(len(matches) <= 1, 'duplicate journal asset')
        if not matches:
            return None
        asset = matches[0]
        release.need(0 < asset['size'] <= 65536,
                     'invalid journal asset state/size')
        match = re.fullmatch(r'https://api.github.com/repos/' + REPOSITORY +
                            r'/releases/assets/([1-9][0-9]*)', asset['apiUrl'])
        release.need(match is not None, 'journal asset belongs to another repository')
        raw = self.command(['api', f'repos/{REPOSITORY}/releases/assets/{match[1]}',
                            '-H', 'Accept: application/octet-stream'])
        release.need(len(raw) == asset['size'] and len(raw) <= 65536 and
                     asset.get('digest') == 'sha256:' + hashlib.sha256(raw).hexdigest(),
                     'journal bytes/digest mismatch')
        return release.parse_json(raw)

    def write(self, kind, phase, record):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / self.name(kind, phase)
            path.write_text(json.dumps(record, indent=2)+'\n')
            # Creation is exclusive at GitHub too. Never use --clobber.
            self.command(['release', 'upload', self.tag, str(path), '--repo', REPOSITORY])
        release.need(self.read(kind, phase) == record, 'journal write not verified')

    def claim(self, kind):
        release.need(self.read(kind, 'claim') is None,
                     'previous submission claim exists without a result; inspect dashboard/receipt, never resend blindly')
        record = dict(schema_version=1, **self.identity, kind=kind, status='submission_unconfirmed')
        self.write(kind, 'claim', record)

    def result(self, kind, file_id, parent=None):
        record = dict(schema_version=1, **self.identity, kind=kind,
                      status='accepted_pending_moderation', file_id=file_id)
        if kind == 'server':
            record['parent_file_id'] = parent
        self.write(kind, 'result', record)


def submit_file(path, project_id, metadata, token, connection_factory=http.client.HTTPSConnection):
    release.token_check(token)
    boundary = 'cf-' + uuid.uuid4().hex
    filename = path.name
    release.need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.zip', filename), 'unsafe upload filename')
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
        'Content-Type: application/json\r\n\r\n' + json.dumps(metadata) +
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        'Content-Type: application/zip\r\n\r\n').encode()
    tail = f'\r\n--{boundary}--\r\n'.encode()
    def body():
        yield head
        with path.open('rb') as handle:
            while chunk := handle.read(1024*1024):
                yield chunk
        yield tail
    connection, phase, status = None, 'connection_setup', None
    try:
        connection = connection_factory(release.HOST, timeout=600)
        phase = 'request'
        connection.request('POST', f'/api/projects/{project_id}/upload-file', body(),
            {'X-Api-Token': token, 'Content-Type': f'multipart/form-data; boundary={boundary}',
             'Content-Length': str(len(head) + path.stat().st_size + len(tail))})
        phase = 'response_headers'
        response = connection.getresponse()
        status = response.status
        if type(status) is not int or not 200 <= status < 300:
            raise release.SubmissionError('http_non_success', phase, status,
                                          release.read_error_summary(response, (token,)))
        phase = 'response_body'
        raw = response.read(65537)
        if len(raw) > 65536:
            raise release.SubmissionError('response_too_large', phase, status)
        try:
            result = release.parse_json(raw)
        except (ValueError, UnicodeError):
            raise release.SubmissionError('invalid_json_response', phase, status) from None
        if not isinstance(result, dict) or not release.positive(result.get('id')):
            raise release.SubmissionError('missing_valid_file_id', phase, status)
        return result['id']
    except release.SubmissionError:
        raise
    except ssl.SSLError:
        raise release.SubmissionError('tls_error', phase, status) from None
    except TimeoutError:
        raise release.SubmissionError('timeout', phase, status) from None
    except OSError:
        raise release.SubmissionError('connection_error', phase, status) from None
    except http.client.HTTPException:
        raise release.SubmissionError('http_protocol_error', phase, status) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except (OSError, http.client.HTTPException):
                pass


def server_metadata(config,version,changelog,parent,manual=False):
    # Child files inherit game versions. Avoid optional name resolution on the
    # parent route. isServerPack is an undocumented hint used by other uploaders;
    # only the read-only publication verifier can confirm actual classification.
    return {'changelog':changelog,'changelogType':'markdown',
        'displayName':f'OKD Server Modpack {version} - Server Pack',
        'releaseType':config['release_type'],'parentFileID':parent,'isServerPack':True,
        'isMarkedForManualRelease':manual}


def publish(client, server, config, version, changelog, identity, known, journal,
            *, mode='client_server', manual=False, token='', uploader=submit_file, receipt=None,
            existing_client_file_id=None, verifier=None):
    def save():
        if receipt:
            receipt.write_text(json.dumps(result, indent=2)+'\n')
    result = dict(schema_version=1, **identity, mode=mode, status='validated',
                  client_file_id=None, server_file_id=None)
    release.need(not known or known.get('version') != version or
                 all(known.get(k) == v for k,v in identity.items()),
                 'published version has different bytes; prepare a new reviewed version')
    save()  # A bad local receipt path stops before any network mutation.
    known_matches = known and all(known.get(k) == v for k, v in identity.items())
    parent = None
    for kind, path in (('client', client), ('server', server)):
        if known_matches and known.get(kind):
            existing = dict(schema_version=1, **identity, kind=kind, **known[kind])
        else:
            existing = journal.read(kind, 'result')
        if kind == 'client' and existing_client_file_id:
            if existing:
                release.need(existing['file_id'] == existing_client_file_id, 'recorded client ID differs')
            else:
                (verifier or verify_existing_client)(existing_client_file_id, config['project_id'], client)
                journal.result('client', existing_client_file_id)
                existing = dict(schema_version=1, **identity, kind='client', file_id=existing_client_file_id)
        if existing:
            file_id = check_record(existing, identity, kind, parent)
        else:
            if kind == 'client' and mode == 'server_only':
                raise release.Invalid('server_only needs a matching recorded client file ID')
            # Token validity/format is checked before taking an irreversible claim.
            release.token_check(token)
            journal.claim(kind)
            result['status'] = 'submission_unconfirmed'
            result['pending_kind'] = kind
            save()
            if kind == 'client':
                metadata = release.metadata(config, changelog)
            else:
                metadata = server_metadata(config,version,changelog,parent,manual)
            metadata['isMarkedForManualRelease'] = manual
            file_id = uploader(path, config['project_id'], metadata, token)
            # Keep accepted ID locally even if durable result upload fails.
            result[kind + '_file_id'] = file_id
            result['status'] = 'accepted_pending_journal'
            save()
            journal.result(kind, file_id, parent)
        result[kind + '_file_id'] = file_id
        result['pending_kind'] = None
        save()
        if kind == 'client':
            parent = file_id
    result['status'] = 'recorded_existing_or_accepted_pending_moderation'
    save()
    return result


def verify_existing_client(file_id, project_id, client):
    release.need(release.positive(file_id), 'existing client ID must be positive')
    def get(host, path, limit):
        conn = http.client.HTTPSConnection(host, timeout=120)
        try:
            conn.request('GET', path, headers={'User-Agent': 'OKD-publication-parent-verifier'})
            response = conn.getresponse()
            release.need(response.status == 200, 'existing client is not publicly verifiable; no retry')
            raw = response.read(limit+1)
            release.need(len(raw) <= limit, 'existing client verification size limit')
            return raw
        finally:
            conn.close()
    row = release.parse_json(get('www.curseforge.com',
        f'/api/v1/mods/{project_id}/files/{file_id}', 1024*1024))
    row = row.get('data', row)
    name = row['fileName']
    release.need(row['id'] == file_id and row['projectId'] == project_id and row['status'] == 4 and
                 row['fileLength'] == client.stat().st_size and isinstance(name,str) and
                 '/' not in name and '\\' not in name and not any(ord(c)<32 for c in name),
                 'existing client file identity/status/size differs')
    raw = get('mediafilez.forgecdn.net',
        f'/files/{file_id//1000}/{file_id%1000}/{quote(name,safe="")}', release.MAX_ZIP)
    release.need(hashlib.sha256(raw).hexdigest() == serverpack.sha(client),
                 'existing CurseForge client bytes differ from verified client ZIP')


def publish_github(client, server, version, client_sha, server_sha, receipt_paths=()):
    tag = 'v' + version
    try:
        raw = subprocess.check_output(['gh', 'release', 'view', tag, '--repo', REPOSITORY,
                                       '--json', 'assets'], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        # Distinguish missing release from transport/auth errors, before creating a tag.
        try:
            subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}'], stderr=subprocess.PIPE)
            response = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/releases/tags/{tag}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            release.need(response.returncode != 0 and b'HTTP 404' in response.stderr,
                         'GitHub release lookup failed; no creation attempted')
            subprocess.run(['gh', 'release', 'create', tag, '--repo', REPOSITORY, '--target',
                os.environ['GITHUB_SHA'], '--title', f'OKD Server Modpack {version}', '--notes',
                'Verified client manifest ZIP and manifest-based server installer input. No MOD JARs bundled. Runtime not yet tested; use a new empty directory.'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            raw = subprocess.check_output(['gh', 'release', 'view', tag, '--repo', REPOSITORY,
                                           '--json', 'assets'], stderr=subprocess.PIPE)
        except (subprocess.CalledProcessError, KeyError):
            raise release.Invalid('GitHub release creation not confirmed; inspect before retry') from None
    assets = release.parse_json(raw)['assets']
    pairs = [(client, client_sha), (server, server_sha)]
    for path in receipt_paths:
        release.need(path.name in ('client.json', 'server.json', 'github-release-receipt.json') and
                     path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024,
                     'invalid provenance receipt upload')
        pairs.append((path, hashlib.sha256(path.read_bytes()).hexdigest()))
    for path, expected in pairs:
        existing = [a for a in assets if a['name'] == path.name]
        if existing:
            release.need(len(existing) == 1 and existing[0]['size'] == path.stat().st_size and
                         existing[0].get('digest') == 'sha256:' + expected,
                         'same-name GitHub asset differs; never overwrite')
        else:
            try:
                subprocess.run(['gh', 'release', 'upload', tag, str(path), '--repo', REPOSITORY],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError:
                raise release.Invalid('GitHub asset upload not confirmed; inspect before retry') from None

    # All durable provenance must exist with exact bytes BEFORE any CF claim/POST.
    try:
        saved = release.parse_json(subprocess.check_output(['gh', 'release', 'view', tag,
            '--repo', REPOSITORY, '--json', 'assets'], stderr=subprocess.PIPE))['assets']
    except subprocess.CalledProcessError:
        raise release.Invalid('GitHub saved assets verification failed; no CurseForge POST') from None
    for path, expected in pairs:
        matches = [a for a in saved if a['name'] == path.name]
        release.need(len(matches) == 1 and matches[0]['size'] == path.stat().st_size and
                     matches[0].get('digest') == 'sha256:' + expected,
                     'published ZIP/source receipt upload not confirmed; no CurseForge POST')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-receipt', type=Path, required=True)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--server-receipt', type=Path, required=True)
    parser.add_argument('--release-receipt', type=Path)
    parser.add_argument('--published-release', action='store_true')
    parser.add_argument('--state', type=Path, default=Path('publication-state.json'))
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--mode', choices=('client_server', 'server_only'), default='client_server')
    parser.add_argument('--manual-release', action='store_true')
    parser.add_argument('--existing-client-file-id', type=int)
    args = parser.parse_args()
    try:
        import native_pack
        inputs = native_pack.load_inputs()
        provenance = None
        if args.release_receipt:
            import published_pack
            provenance = release.parse_json(args.release_receipt.read_bytes())
            inputs = published_pack.validate_receipt(provenance, args.client,
                release.parse_json(args.client_receipt.read_bytes()), args.server,
                release.parse_json(args.server_receipt.read_bytes()), published=args.published_release)
        release.need(not args.published_release or provenance is not None, 'published source receipt required')
        meta, refs, overrides, source_sha = inputs
        client_sha = native_pack.verify_client(args.client,
            release.parse_json(args.client_receipt.read_bytes()), inputs)
        policy = native_pack.policy(overrides)
        configs = {'client': native_pack.runtime_config(meta, client_sha)}
        lock = {'version': meta['version']}
        server = release.parse_json(args.server_receipt.read_bytes())
        serverpack.verify_prepared(args.server, server, args.client,
            policy, lock['version'], refs)
        identity = fingerprint(configs['client']['project_id'], lock['version'], client_sha, server['sha256'])
        known = release.parse_json(args.state.read_bytes()) if args.state.exists() else None
        if not args.submit:
            dry = dict(schema_version=1, **identity, status='dry_run_read_only' if args.published_release else 'dry_run_no_network', mode=args.mode,
                       release_source_commit=provenance.get('source_commit') if provenance else None,
                       published_release_bytes=args.published_release,
                       manual_release=args.manual_release,
                       existing_client_file_id=args.existing_client_file_id,
                       published_version_blocks_changed_bytes=bool(known and known.get('version') == lock['version'] and any(known.get(k) != v for k,v in identity.items())),
                       existing_state_matches=bool(known and all(known.get(k) == v for k,v in identity.items())),
                       client_metadata=dict(release.metadata(configs['client'], Path('CHANGELOG.md').read_text()),
                           isMarkedForManualRelease=args.manual_release) if args.mode == 'client_server' else None,
                       server_metadata=server_metadata(configs['client'],lock['version'],Path('CHANGELOG.md').read_text(),'recorded-or-returned-client-file-id',args.manual_release))
            with args.receipt.open('x') as handle:
                json.dump(dry, handle, indent=2); handle.write('\n')
            print('DRY RUN: both ZIPs verified; no network mutation or upload.')
            return 0
        release.need(provenance is not None, 'exact release source/ZIP receipt required before submission')
        release.need(release.positive(configs['client']['project_id']) and configs['client']['project_id'] != 1733082, 'actual OKD project_id is required before submission')
        release.need(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'submission is main-only')
        release.need(os.environ.get('CURSEFORGE_SUBMISSION_ENABLED') == 'true', 'submission is disabled')
        release.need(not args.receipt.exists(), 'use a new receipt path')
        release.need(not known or known.get('version') != lock['version'] or
            all(known.get(k) == v for k,v in identity.items()),
            'published version has different bytes; no GitHub or CurseForge mutation allowed')
        release.token_check(os.environ.get('CURSEFORGE_API_TOKEN', ''))
        import diagnose_api
        audit = diagnose_api.audit(os.environ.get('CURSEFORGE_API_TOKEN', ''))
        if (audit['status'] != 'read_complete' or audit.get('missing_names') != [] or
                audit.get('category') not in ('all_metadata_names_exist', 'all_metadata_names_present_with_variants')):
            with args.receipt.open('x') as handle:
                json.dump(dict(schema_version=1, **identity, status='authentication_preflight_failed',
                    audit=audit), handle, indent=2)
            raise release.Invalid('read-only Upload API audit failed; no publication attempted')
        publish_github(args.client, args.server, lock['version'], client_sha, server['sha256'],
            receipt_paths=(args.client_receipt, args.server_receipt, args.release_receipt))
        result = publish(args.client, args.server, configs['client'], lock['version'],
            Path('CHANGELOG.md').read_text(), identity, known,
            GitHubJournal('v'+lock['version'], identity), mode=args.mode,
            existing_client_file_id=args.existing_client_file_id,
            manual=args.manual_release, token=os.environ.get('CURSEFORGE_API_TOKEN', ''), receipt=args.receipt)
        print(json.dumps(result, indent=2))
    except release.SubmissionError as error:
        if args.receipt.exists():
            record = release.parse_json(args.receipt.read_bytes())
            record['error'] = error.diagnostics
            args.receipt.write_text(json.dumps(record, indent=2)+'\n')
        print('STOP:', error)
        return 1
    except (release.Invalid, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        print('STOP: publication not confirmed; preserve receipts and check dashboard before retry.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
