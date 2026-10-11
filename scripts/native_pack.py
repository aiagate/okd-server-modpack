"""Repository-owned fixed references/settings -> standard packwiz CF export.

No App export is needed for ordinary builds. Never patch a generated manifest.
Temporary packwiz metadata is export-only; no fake MOD hashes or downloads.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

import release as r
import pack_io as pack

MODULE='v0.0.0-20260218225342-dfd8b68a4796'
MODULE_SUM='h1:e6WSGD9fo7V8sbxGNOZiBHX6HnlBezOcQxVBZD6R0fM='
GO_VERSION='1.27.2'


def digest(blob): return hashlib.sha256(blob).hexdigest()


def load_inputs(root=Path('pack')):
    r.need(root.is_dir() and not root.is_symlink() and
        (root/'overrides').is_dir() and not (root/'overrides').is_symlink(), 'regular source directories required')
    for name in ('release.json','client.refs.json','server.refs.json','migration.json'):
        path=root/name
        r.need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2*1024*1024,
            'regular bounded source metadata required')
    meta=r.parse_json((root/'release.json').read_bytes())
    r.need(set(meta)=={'schema_version','version','name','author','minecraft_version','loader_id',
        'project_id','game_version_names','release_type'} and meta['schema_version']==1,
        'invalid repository release metadata')
    r.need(isinstance(meta['version'],str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?',meta['version']),
        'invalid release version')
    refs={k:pack.reference_map(r.parse_json((root/f'{k}.refs.json').read_bytes())['files']) for k in pack.KINDS}
    r.need(set(refs['server'])<=set(refs['client']) and
        all(refs['client'][k]==v for k,v in refs['server'].items()),'server references must be an exact client subset')
    r.need(all(set(f)=={'projectID','fileID','required'} and f['required'] for rows in refs.values() for f in rows.values()),
        'use pinned required CurseForge references')
    overrides={}
    for path in sorted((root/'overrides').rglob('*')):
        r.need(not path.is_symlink(), 'source symlink forbidden')
        if path.is_file(): overrides[path.relative_to(root).as_posix()]=path.read_bytes()
    r.need(overrides,'reviewed repository overrides required')
    migration=r.parse_json((root/'migration.json').read_bytes())
    r.need(migration['schema_version']==1 and migration['module_version']==MODULE and
        migration['go_version']==GO_VERSION,'builder pin differs')
    if meta['version']==migration['migration_version']:
        r.need({n:digest(b) for n,b in overrides.items()}==migration['override_sha256'],
            'initial migration overrides differ from reviewed repository source')
        for kind in pack.KINDS:
            r.need(digest(json.dumps(refs[kind],sort_keys=True).encode())==migration['reference_sha256'][kind],
                'initial migration reference difference')
    hashes={n:digest(b) for n,b in overrides.items()}
    source_sha=digest(json.dumps({'metadata':meta,'refs':refs,'overrides':hashes},sort_keys=True).encode())
    cfg=runtime_config(meta,'0'*64)
    r.config_check(cfg, allow_unconfigured=True)
    return meta,refs,overrides,source_sha


def runtime_config(meta,client_sha):
    return {'project_id':meta['project_id'],'minecraft_version':meta['minecraft_version'],
        'loader_id':meta['loader_id'],'game_version_names':meta['game_version_names'],
        'release_type':meta['release_type'],'display_name':f'{meta["name"]} {meta["version"]}',
        'reviewed_sha256':client_sha}


def policy(overrides):
    return {'override_sha256':{'client':{n:digest(b) for n,b in overrides.items()}}}


def verify_tool(binary,go='go'):
    raw=subprocess.check_output([go,'version','-m',str(binary)],stderr=subprocess.PIPE).decode()
    r.need(re.search(r'\bgo'+re.escape(GO_VERSION)+r'\b',raw) and
        f'\tmod\tgithub.com/packwiz/packwiz\t{MODULE}\t{MODULE_SUM}' in raw,
        'packwiz binary module/compiler does not match the pin')


def stage(root,meta,refs,overrides):
    for name,blob in overrides.items():
        path=root/name.removeprefix('overrides/'); path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
    (root/'mods').mkdir(exist_ok=True)
    for pid,f in refs['client'].items():
        side='both' if pid in refs['server'] else 'client'
        # CF export consumes only IDs. No dependency resolution or fabricated hashes.
        text=f'name = "CurseForge project {pid}"\nside = "{side}"\npin = true\n[update.curseforge]\nproject-id = {pid}\nfile-id = {f["fileID"]}\n'
        (root/'mods'/f'{pid}.pw.toml').write_text(text)
    index=b'hash-format = "sha256"\n'; (root/'index.toml').write_bytes(index)
    loader,version=meta['loader_id'].split('-',1)
    toml=f'name = {json.dumps(meta["name"])}\nauthor = {json.dumps(meta["author"])}\nversion = {json.dumps(meta["version"])}\npack-format = "packwiz:1.1.0"\n[index]\nfile = "index.toml"\nhash-format = "sha256"\nhash = "{digest(index)}"\n[versions]\nminecraft = {json.dumps(meta["minecraft_version"])}\n{loader} = {json.dumps(version)}\n'
    (root/'pack.toml').write_text(toml)


def canonical_zip(raw,output):
    r.need(not output.exists(),'use a new build output')
    with zipfile.ZipFile(raw) as old,output.open('xb') as handle,zipfile.ZipFile(handle,'w') as new:
        r.need(len(old.namelist())==len(set(old.namelist())),'duplicate exporter entries')
        for info in sorted(old.infolist(),key=lambda i:i.filename):
            if info.is_dir(): continue
            # Repackage entry bytes unchanged; never edit exporter manifest/modlist.
            entry=zipfile.ZipInfo(info.filename,(2000,1,1,0,0,0));entry.create_system=3
            entry.external_attr=0o100644<<16;entry.compress_type=zipfile.ZIP_STORED
            new.writestr(entry,old.read(info))


def verify_client(client,receipt,inputs):
    meta,refs,overrides,source_sha=inputs
    blob=pack.read_blob(client); sha=digest(blob); cfg=runtime_config(meta,sha)
    r.validate(blob,cfg,allow_unconfigured=True) # CRC/bounds/path/private data/comment exceptions.
    with zipfile.ZipFile(client) as archive:
        manifest_blob=archive.read('manifest.json'); manifest=r.parse_json(manifest_blob)
        actual=pack.reference_map(manifest['files'])
        r.need(actual==refs['client'],'generated MOD reference difference')
        r.need(manifest['name']==meta['name'] and manifest['version']==meta['version'] and
            manifest['author']==meta['author'],'generated identity differs')
        names={n for n in archive.namelist() if not n.endswith('/')}
        r.need(names==set(overrides)|{'manifest.json','modlist.html'},'unexpected generated entry')
        for n,expected in overrides.items():
            r.need(not pack.UNWANTED.search(n) and archive.read(n)==expected,'generated settings differ/unwanted state')
        r.need(receipt.get('schema_version')==1 and receipt.get('exporter')=='packwiz' and
            receipt.get('module_version')==MODULE and receipt.get('version')==meta['version'] and
            receipt.get('source_sha256')==source_sha and receipt.get('sha256')==sha and
            receipt.get('size_bytes')==len(blob) and receipt.get('filename')==client.name and
            receipt.get('manifest_sha256')==digest(manifest_blob) and
            receipt.get('modlist_sha256')==digest(archive.read('modlist.html')),
            'build receipt does not match source/bytes')
    return sha


def build(root,output,binary,go='go'):
    inputs=load_inputs(root);meta,refs,overrides,source_sha=inputs
    r.need(not output.exists(),'use new build directory');output.mkdir(parents=True)
    verify_tool(binary,go)
    with tempfile.TemporaryDirectory() as temp:
        work=Path(temp); stage(work,meta,refs,overrides)
        raw=work/'export.zip'
        subprocess.run([str(binary.resolve()),'--pack-file',str(work/'pack.toml'),'curseforge','export',
            '--side','client','--output',str(raw)],cwd=work,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        client=output/f'okd-server-modpack-{meta["version"]}.zip'
        canonical_zip(raw,client)
    with zipfile.ZipFile(client) as archive:
        receipt=dict(schema_version=1,exporter='packwiz',module_version=MODULE,version=meta['version'],
            source_sha256=source_sha,sha256=digest(client.read_bytes()),size_bytes=client.stat().st_size,
            filename=client.name,manifest_sha256=digest(archive.read('manifest.json')),
            modlist_sha256=digest(archive.read('modlist.html')),runtime_verified=False)
    verify_client(client,receipt,inputs)
    (output/'client.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return client,receipt


def compare_builds(a,b):
    # Upstream iterates Go maps: reference/modlist order may vary. Preserve its
    # manifest bytes, compare semantics, and publish only the saved run artifact.
    for report in ('client.json','server.json'):
        left=r.parse_json((a/report).read_bytes());right=r.parse_json((b/report).read_bytes())
        r.need(left['version']==right['version'],'rebuild version differs')
        with zipfile.ZipFile(a/left['filename']) as x,zipfile.ZipFile(b/right['filename']) as y:
            r.need(set(x.namelist())==set(y.namelist()),'rebuild entry set differs')
            for name in x.namelist():
                if name in ('manifest.json','client/manifest.json'):
                    m=r.parse_json(x.read(name));n=r.parse_json(y.read(name))
                    m['files']=sorted(m['files'],key=lambda f:f['projectID'])
                    n['files']=sorted(n['files'],key=lambda f:f['projectID'])
                    r.need(m==n,'rebuild manifest content differs')
                elif name=='modlist.html':
                    r.need(sorted(x.read(name).splitlines())==sorted(y.read(name).splitlines()),'rebuild MOD list differs')
                else:
                    r.need(x.read(name)==y.read(name),'rebuild settings differ')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('pack'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--packwiz',type=Path,required=True)
    parser.add_argument('--go',default='go')
    args=parser.parse_args()
    try:
        client,receipt=build(args.root,args.output,args.packwiz,args.go)
        import serverpack
        meta,refs,overrides,source_sha=load_inputs(args.root)
        server=args.output/f'okd-server-modpack-{meta["version"]}-serverpack.zip'
        serverpack.write_zip(server,serverpack.blobs(client,policy(overrides),refs,meta['version']))
        record=dict(schema_version=1,version=meta['version'],client_sha256=receipt['sha256'],
            sha256=serverpack.sha(server),size_bytes=server.stat().st_size,filename=server.name,
            format='manifest-installer-input',runtime_verified=False)
        serverpack.verify_prepared(server,record,client,policy(overrides),meta['version'],refs)
        (args.output/'server.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps({'client':receipt,'server':record},indent=2))
    except (r.Invalid,OSError,ValueError,KeyError,subprocess.CalledProcessError,zipfile.BadZipFile):
        print('STOP: repository build failed; no publication performed.')
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
