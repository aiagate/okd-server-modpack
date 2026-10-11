"""Shared manifest safety checks, upload metadata and redacted API diagnostics."""
import hashlib
import html
import http.client
import io
import json
from pathlib import Path
import re
import stat
import zipfile

MAX_ZIP = 90 * 1024 * 1024  # Repository policy, not a CurseForge API limit.
MAX_TOTAL = 256 * 1024 * 1024
MAX_ENTRY = 32 * 1024 * 1024
MAX_ENTRIES = 10000
HOST = 'minecraft.curseforge.com'
REVIEWED_COMMENTS_PATH = Path(__file__).with_name('reviewed_comments.json')
DENIED = {'saves', 'world', 'worlds', 'logs', 'crash-reports', 'screenshots',
          'backups', 'options.txt', 'optionsof.txt', 'servers.dat', 'servers.dat_old',
          'server.properties', 'whitelist.json', 'ops.json', 'usercache.json',
          'secrets', 'credentials', 'session.lock', 'level.dat', 'playerdata'}
SENSITIVE = re.compile(rb'(?i)(-----BEGIN [A-Z ]*PRIVATE KEY|'
                       rb'(?:password|passwd|token|api[_-]?key|secret)\s*["\x27]?\s*[:=]\s*["\x27]?[^\s"\x27,}]{4,}|'
                       rb'https?://|(?:\d{1,3}\.){3}\d{1,3}|'
                       rb'(?:localhost|[a-z0-9.-]+\.(?:local|lan|internal))\b)')
PUBLIC_MODLIST_URL = re.compile(
    rb'https?://(?:(?:www|minecraft)\.)?curseforge\.com/'
    rb'(?:minecraft/(?:mc-mods|shaders)/[a-z0-9-]+(?:/files/[0-9]+)?|projects/[a-z0-9-]+)/?'
    rb'(?=[\s"\x27<>]|$)', re.IGNORECASE)


class Invalid(ValueError):
    pass


class SubmissionError(Invalid):
    """Bounded allowlisted diagnostics; never retain raw bodies or exceptions."""

    def __init__(self, category, phase, http_status=None, response_summary=None):
        self.diagnostics = {'category': category, 'phase': phase,
                            'http_status': http_status, 'response_body_recorded': False}
        if response_summary is not None:
            self.diagnostics['response_summary'] = response_summary
        status = f', HTTP {http_status}' if http_status is not None else ''
        super().__init__(f'Submission not confirmed ({category}, {phase}{status}). '
                         'Check author dashboard before any manual retry.')


def need(ok, message):
    if not ok:
        raise Invalid(message)


def positive(value):
    return type(value) is int and value > 0


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'JSON has duplicate keys')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def config_check(config, *, allow_unconfigured=False):
    need(isinstance(config, dict), 'config must be an object')
    need(set(config) == {'project_id', 'minecraft_version', 'loader_id',
                        'game_version_names', 'release_type', 'display_name',
                        'reviewed_sha256'}, 'invalid runtime validation config keys')
    need(positive(config['project_id']) or (allow_unconfigured and config['project_id'] is None), 'project_id is not configured')
    need(config['project_id'] != 1733082, 'Shimae project is forbidden for OKD releases')
    for key in ('minecraft_version', 'loader_id', 'display_name'):
        need(isinstance(config[key], str) and config[key].strip() and
             'REPLACE' not in config[key] and len(config[key]) < 200,
             key + ' is not configured')
    need(config['release_type'] in ('alpha', 'beta', 'release'), 'invalid release_type')
    names = config['game_version_names']
    need(isinstance(names, list) and len(names) == 3 and
         all(isinstance(n, str) for n in names), 'set exactly Minecraft, loader, Client game version names')
    family = config['loader_id'].split('-')[0]
    loader_name = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric',
                   'quilt': 'Quilt'}.get(family)
    need(loader_name is not None and config['loader_id'].startswith(family + '-'), 'unsupported loader ID')
    need(set(names) == {config['minecraft_version'], loader_name, 'Client'},
         'game_version_names must match Minecraft version, loader and Client')
    need(isinstance(config['reviewed_sha256'], str) and
         re.fullmatch('[0-9a-f]{64}', config['reviewed_sha256']),
         'reviewed_sha256 must identify the verified client ZIP')


def checked_override(content, name):
    """Do not skip comments generically; exempt only reviewed exact comment lines."""
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        raise Invalid('binary overrides require a separately reviewed policy') from None
    need(b'\x00' not in content, 'override contains a possible credential or connection destination')
    # Credential detection applies even to an approved documentation comment.
    credentials = re.compile(rb'(?i)(-----BEGIN [A-Z ]*PRIVATE KEY|'
        rb'(?:password|passwd|token|api[_-]?key|secret)\s*["\x27]?\s*[:=]\s*["\x27]?[^\s"\x27,}]{4,})')
    need(not credentials.search(content), 'override contains a possible credential')
    policy = parse_json(REVIEWED_COMMENTS_PATH.read_bytes())
    approved = policy.get(name, [])
    for line in text.splitlines():
        raw = line.strip().encode('utf-8')
        reviewed = raw.startswith(b'#') and hashlib.sha256(raw).hexdigest() in approved
        need(reviewed or not SENSITIVE.search(raw),
             'override contains a possible credential or connection destination')


def validate(blob, config, *, allow_unconfigured=False):
    config_check(config, allow_unconfigured=allow_unconfigured)
    need(len(blob) <= MAX_ZIP, 'ZIP exceeds 90 MiB repository limit')
    digest = hashlib.sha256(blob).hexdigest()
    need(digest == config['reviewed_sha256'], 'ZIP differs from reviewed_sha256')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        need(0 < len(entries) <= MAX_ENTRIES, 'invalid ZIP entry count')
        need(sum(e.file_size for e in entries) <= MAX_TOTAL, 'expanded ZIP exceeds 256 MiB')
        seen = set()
        manifest = None
        for entry in entries:
            name = entry.filename
            parts = name.rstrip('/').split('/')
            need(name == entry.orig_filename and '\\' not in name and ':' not in name and
                 all(p not in ('', '.', '..') for p in parts) and
                 all(ord(c) >= 32 and ord(c) != 127 for c in name), 'unsafe ZIP path')
            normalized = name.rstrip('/').casefold()
            need(normalized not in seen, 'duplicate ZIP path')
            seen.add(normalized)
            mode = entry.external_attr >> 16
            need(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'special ZIP entry')
            need(not entry.flag_bits & 1, 'encrypted ZIP entry')
            need(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'unsupported ZIP compression')
            need(entry.file_size <= MAX_ENTRY and
                 entry.file_size <= max(entry.compress_size, 1) * 200, 'ZIP entry size/ratio limit')
            need(parts[0] == 'overrides' or name in ('manifest.json', 'modlist.html'),
                 'ZIP must have manifest.json, optional modlist.html, and overrides only')
            lower = [p.casefold() for p in parts]
            need(not any(p in DENIED or p.startswith('.') or
                         p.endswith(('.pem', '.key', '.log', '.mca', '.jar', '.zip', '.7z'))
                         for p in lower), 'private/runtime/binary archive content is forbidden')
            if entry.is_dir():
                need(entry.file_size == 0, 'nonempty ZIP directory')
                continue
            need(name != 'overrides', 'overrides must be a directory')
            content = archive.read(entry)  # Verify CRC; never extract.
            if name == 'manifest.json':
                need(len(content) <= 2 * 1024 * 1024, 'manifest too large')
                manifest = parse_json(content)
                # Inspect normalized JSON so escaped keys/values cannot bypass scans.
                canonical = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
                need(not SENSITIVE.search(canonical),
                     'manifest contains a possible credential or connection destination')
            elif name == 'modlist.html':
                try:
                    text = html.unescape(content.decode('utf-8')).encode('utf-8')
                except UnicodeDecodeError:
                    raise Invalid('modlist.html must be UTF-8 text') from None
                # App mod lists contain public project links; no arbitrary URL exemption.
                inspected = PUBLIC_MODLIST_URL.sub(b'', text)
                need(b'\x00' not in text and not SENSITIVE.search(inspected),
                     'modlist contains a possible credential or connection destination')
            elif parts[0] == 'overrides':
                checked_override(content, name)
        need(isinstance(manifest, dict), 'root manifest.json missing or invalid')
        need(any(e.filename == 'overrides/' and e.is_dir() or
                 e.filename.startswith('overrides/') and len(e.filename) > len('overrides/')
                 for e in entries), 'overrides directory missing')
        need(manifest.get('manifestType') == 'minecraftModpack' and
             type(manifest.get('manifestVersion')) is int and manifest['manifestVersion'] == 1,
             'unsupported manifest format')
        need(manifest.get('overrides') == 'overrides', 'unsupported overrides directory')
        for field in ('name', 'version'):
            need(isinstance(manifest.get(field), str) and manifest[field].strip(), 'manifest identity missing')
        # App exports may contain an empty author; attribution is confirmed
        # separately. Do not rewrite the generated manifest to satisfy our checker.
        need(isinstance(manifest.get('author'), str), 'manifest author must be a string')
        need(not manifest['version'].startswith('0.0.0-local.') and
             all('REPLACE' not in manifest[field] for field in ('name', 'version', 'author')),
             'local reconstruction draft or placeholder identity cannot be submitted')
        minecraft = manifest.get('minecraft')
        need(isinstance(minecraft, dict) and minecraft.get('version') == config['minecraft_version'],
             'Minecraft version differs from export')
        loaders = minecraft.get('modLoaders')
        need(isinstance(loaders, list) and len(loaders) == 1 and isinstance(loaders[0], dict) and
             loaders[0].get('id') == config['loader_id'] and loaders[0].get('primary') is True,
             'loader differs from export (one primary loader required)')
        files = manifest.get('files')
        need(isinstance(files, list) and files, 'manifest files must be a nonempty list')
        ids = set()
        for item in files:
            need(isinstance(item, dict) and positive(item.get('projectID')) and
                 positive(item.get('fileID')) and type(item.get('required')) is bool,
                 'invalid manifest file reference')
            need(item['projectID'] not in ids, 'duplicate project reference')
            ids.add(item['projectID'])
    return digest


def metadata(config, changelog):
    need(changelog.strip() and 'REPLACE_ME' not in changelog and len(changelog.encode()) <= 100000,
         'write a release changelog (up to 100 KB)')
    return {'changelog': changelog, 'changelogType': 'markdown',
            'displayName': config['display_name'], 'releaseType': config['release_type'],
            'gameVersionNames': config['game_version_names'], 'isMarkedForManualRelease': True}


def token_check(token):
    need(token and token.strip() == token and not any(ord(c) < 32 for c in token),
         'CURSEFORGE_API_TOKEN is not configured or invalid')


ERROR_FIELDS = frozenset(('metadata', 'file', 'projectId', 'projectID', 'changelog',
                         'changelogType', 'displayName', 'gameVersions', 'gameVersionNames',
                         'releaseType', 'isMarkedForManualRelease', 'parentFileID', 'relations'))
ERROR_CODES = frozenset(('required', 'invalid', 'invalid_value', 'not_found',
                        'unknown_game_version', 'invalid_game_version', 'invalid_release_type',
                        'invalid_metadata', 'project_not_approved', 'bad_request',
                        'unauthorized', 'forbidden', 'invalid_api_token', 'token_expired'))
MESSAGE_HINTS = {
    'malformed_authentication': re.compile(r'(?:parse|decode|malformed|format).{0,40}(?:token|api.?key)|'
                                         r'(?:token|api.?key).{0,40}(?:parse|decode|malformed|format)'),
    'invalid_authentication': re.compile(r'(?:invalid|expired|revoked|not valid).{0,40}(?:token|api.?key)|'
                                         r'(?:token|api.?key).{0,40}(?:invalid|expired|revoked|not valid)'),
    'missing_authentication': re.compile(r'(?:missing|required|not provided).{0,40}(?:token|api.?key)|'
                                         r'(?:token|api.?key).{0,40}(?:missing|required|not provided)'),
    'invalid_header': re.compile(r'(?:invalid|malformed).{0,40}header|header.{0,40}(?:invalid|malformed)'),
    'invalid_game_version': re.compile(r'(?:invalid|unknown|not found).{0,40}game.?version|'
                                      r'game.?version.{0,40}(?:invalid|unknown|not found)'),
    'project_not_approved': re.compile(r'project.{0,40}(?:not approved|unapproved|pending approval)'),
}


# Known protocol vocabulary only. Unknown reflected values are never retained.
ERROR_MESSAGE_WORDS = set(('a an the this that of to for from as at by in on with and or but '
    'is are was were be been being not no only must should can cannot could may will '
    'file files parent child project projects upload uploaded uploading additional server pack '
    'invalid valid validation error errors failed failure required missing found exist exists '
    'does do have has already duplicate approved approval rejected pending processing review '
    'status id ids metadata game version versions name names release type changelog extension '
    'permission permissions authorized unauthorized authentication api token key credentials '
    'provided specified supported unsupported allowed notallowed empty null request response '
    'size large small length limit exceeds contain contains expected match matches belong belongs '
    'use used set value values Please please try again before after until wait needs need '
    'parentfileid isserverpack gameversions gameversionnames releasetype displayname '
    'changelogtype ismarkedformanualrelease minecraft neoforge client').lower().split())


def diagnostic_message(message, secrets=()):
    if not isinstance(message,str) or len(message)>4096:
        return None
    for secret in secrets:
        if secret:
            message=message.replace(secret,'[redacted]')
    message=re.sub(r'https?://\S+|\S+@\S+|(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z]:[\\/]\S+|/\S+', '[redacted]', message)
    tokens=re.findall(r'[A-Za-z][A-Za-z0-9_-]*|[0-9]+|[.,:;!?()]',message)
    kept=[];meaningful=False
    for word in tokens[:128]:
        if word.lower() in ERROR_MESSAGE_WORDS:
            kept.append(word);meaningful=True
        elif word in '.,:;!?()':
            kept.append(word)
        elif not kept or kept[-1]!='[redacted]':
            kept.append('[redacted]')
    return ' '.join(kept)[:512] if meaningful else None


def safe_api_error(raw, secrets=()):
    """Allow known fields/codes and redacted protocol vocabulary, never raw bodies."""
    summary = {'response_format': 'too_large' if len(raw) > 65536 else 'non_json',
               'validation_fields': [], 'validation_codes': []}
    if len(raw) > 65536:
        return summary
    try:
        data = parse_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        return summary
    summary['response_format'] = 'json_object' if isinstance(data, dict) else 'json_other'
    if not isinstance(data, dict):
        return summary
    fields, codes = set(), set()
    hints = set()
    messages = set()

    def field(value):
        if not isinstance(value, str):
            return
        match = re.fullmatch(r'(?:metadata\.)?([A-Za-z]+)(?:\[[0-9]{1,6}\])?', value, re.IGNORECASE)
        aliases = {name.lower(): name for name in ERROR_FIELDS}
        if match and match[1].lower() in aliases:
            fields.add(aliases[match[1].lower()])

    def entry(value):
        if not isinstance(value, dict):
            return
        field(value.get('field'))
        for key in ('message','errorMessage','Message','ErrorMessage'):
            safe=diagnostic_message(value.get(key),secrets)
            if safe and len(messages)<8: messages.add(safe)
        code = value.get('code')
        if isinstance(code, str) and code in ERROR_CODES:
            codes.add(code)

    # Only known containers/keys are traversed. A small integer in a dedicated
    # errorCode field is a protocol code, not an arbitrary numeric response value.
    def known_error(value, depth=0):
        if not isinstance(value, dict) or depth > 3:
            return
        for key in ('errorCode', 'ErrorCode'):
            code = value.get(key)
            if type(code) is int and 0 <= code <= 9999:
                summary['error_code'] = code
        for key in ('errorMessage', 'ErrorMessage', 'message', 'Message'):
            message = value.get(key)
            if isinstance(message, str):
                safe = diagnostic_message(message, secrets)
                if safe and len(messages)<8: messages.add(safe)
                # Email/domain/URL suffixes such as .invalid must not be
                # mistaken for a server validation sentence.
                message = re.sub(r'\S+@\S+|https?://\S+', '', message.lower())
                for category, pattern in MESSAGE_HINTS.items():
                    if pattern.search(message):
                        hints.add(category)
        for key in ('error', 'Error', 'details', 'Details'):
            known_error(value.get(key), depth + 1)

    entry(data)
    known_error(data)
    for key in ('errors', 'validationErrors', 'ModelState'):
        errors = data.get(key)
        if isinstance(errors, dict):
            for name, values in errors.items():
                field(name)
                if isinstance(values, list):
                    for value in values:
                        entry(value)
                else:
                    entry(values)
        elif isinstance(errors, list):
            for value in errors:
                entry(value)
    summary.update(validation_fields=sorted(fields), validation_codes=sorted(codes))
    if messages:
        summary['diagnostic_messages'] = sorted(messages)
        summary['message_values_redacted'] = True
    if hints:
        # These fixed labels are text-derived hints, not claimed official codes.
        summary['message_hints'] = sorted(hints)
    return summary


def read_error_summary(response, secrets=()):
    try:
        return safe_api_error(response.read(65537), secrets)
    except (OSError, http.client.HTTPException):
        return {'response_format': 'read_failed', 'validation_fields': [], 'validation_codes': []}
