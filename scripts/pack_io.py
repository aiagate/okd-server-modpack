"""Shared fixed-reference and bounded ZIP input checks."""
import re
from release import MAX_ZIP, need, positive

KINDS = ('client', 'server')
UNWANTED = re.compile(r'(?i)(?:/benchmarks?/|/chunky/(?:tasks/|[^/]+\.(?:csv|properties)$)|sodium-fingerprint\.json$|'
                      r'\.bak(?:\.|$))')


def reference_map(files):
    need(isinstance(files, list) and files, 'reference lock must contain files')
    result = {}
    for item in files:
        need(isinstance(item, dict) and set(item) == {'projectID', 'fileID', 'required'}
             and positive(item.get('projectID')) and positive(item.get('fileID'))
             and type(item.get('required')) is bool,
             'invalid locked MOD reference')
        need(item['projectID'] not in result, 'duplicate locked MOD reference')
        result[item['projectID']] = item
    return result


def read_blob(path):
    need(path.is_file() and not path.is_symlink() and path.suffix == '.zip', 'use a regular manifest ZIP')
    with path.open('rb') as handle:
        return handle.read(MAX_ZIP + 1)
