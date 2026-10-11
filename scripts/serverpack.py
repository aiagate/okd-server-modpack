"""Build a lightweight installer input from a verified client manifest.

The standard itzg AUTO_CURSEFORGE installer fetches pinned MODs at deployment.
This ZIP is not a preassembled, immediately executable Java server.
"""
import hashlib
import json
import re
import zipfile

import release


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


EXCLUDED_CONFIGS = frozenset(('MouseTweaks.cfg', 'aeronautics_windsound-client.toml',
    'entityculling.json', 'gpushift-client.toml', 'iris-excluded.json', 'iris.properties',
    'skinlayers.json', 'sodium-mixins.properties', 'sodium-options.json'))


def blobs(client, policy, refs, version):
    release.need(isinstance(version,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',version),
                 'unsafe release version')
    with zipfile.ZipFile(client) as archive:
        manifest = archive.read('manifest.json')
        release.need(release.parse_json(manifest)['version'] == version, 'client manifest version mismatch')
        # Use the reviewed server refs/settings.
        paths = {n:h for n,h in policy['override_sha256']['client'].items()
                 if n.startswith('overrides/config/') and
                 n.removeprefix('overrides/config/') not in EXCLUDED_CONFIGS}
        notices = {n:h for n,h in policy['override_sha256']['client'].items()
                   if n in ('overrides/LICENSE-OKD.txt','overrides/THIRD-PARTY-NOTICES.txt')}
        release.need(all(n.startswith('overrides/config/') for n in paths),
                     'server settings must be reviewed config paths')
        paths.update(notices)
        files = {n: archive.read(n) for n in paths}
        release.need(all(hashlib.sha256(files[n]).hexdigest() == h for n,h in paths.items()),
                     'server config differs from the verified client; review policy first')
        files['manifest.json'] = manifest
        files['modlist.html'] = archive.read('modlist.html')
    excluded = sorted(set(refs['client']) - set(refs['server']))
    included = sorted(refs['server'])
    name = f'okd-server-modpack-{version}-serverpack.zip'
    files['compose.yaml'] = (f'''services:
  minecraft:
    image: itzg/minecraft-server:java21
    environment:
      EULA: "${{EULA:?Review Minecraft EULA and set EULA explicitly}}"
      TYPE: AUTO_CURSEFORGE
      MEMORY: "${{MEMORY:-4G}}"
      CF_SLUG: okd-server-modpack
      CF_MODPACK_ZIP: /pack/{name}
      CF_EXCLUDE_INCLUDE_FILE: ""
      CF_EXCLUDE_MODS: "{','.join(map(str,excluded))}"
      CF_FORCE_INCLUDE_MODS: "{','.join(map(str,included))}"
    ports:
      - "${{MC_PORT:-25565}}:25565"
    volumes:
      - ./:/pack:ro
      - ./downloads:/downloads:ro
      - server-data:/data
volumes:
  server-data:
''').encode()
    files['SERVER-REFERENCES.json'] = (json.dumps({'schema_version':1,'version':version,
        'files':list(refs['server'].values()), 'excluded_project_ids':excluded},indent=2)+'\n').encode()
    files['README-SERVER.md'] = f'''# OKD Server Modpack {version}: manifest-based server setup

This is installer input, not a standalone preassembled ServerPack. No MOD JARs,
Java runtime, world, credentials or EULA acceptance are bundled. manifest.json
is byte-for-byte the verified client manifest; SERVER-REFERENCES.json records
which pinned references are intended for the server. The compose example uses
the standard itzg AUTO_CURSEFORGE installer, not a custom downloader.

1. Use a new empty directory, copy {name} into it, and extract it there.
   Keep the original ZIP next to compose.yaml; the installer reads that ZIP.
2. Create an empty downloads directory. Review Minecraft EULA and explicitly
   set EULA=true yourself if you agree. Do not reuse an existing production data
   directory for the first test. Compose creates a project-specific named volume.
3. Run docker compose up -d. TrueNAS users can use a separate Custom App with
   equivalent read-only pack/download mounts and a fresh /data dataset.
   The compose example needs Docker Compose; importing a ZIP into the CurseForge
   App alone does not install or launch this server.
4. AUTO_CURSEFORGE downloads pinned MODs and the manifest's loader. If it reports
   files unavailable through automatic downloads, download those exact files
   using CurseForge in a browser and put them in downloads, then restart.
5. Check logs before connecting with the matching client. Set port, memory and
   host paths for your environment.

Existing world migration is a separate operation: this ZIP contains neither
the world nor server.properties and does not move them. Legacy CURSEFORGE can
run below CF_BASE_DIR (by default /data/FeedTheBeast), while AUTO_CURSEFORGE
installs into /data. Identify the actual working directory and level-name first.
Use a consistent stopped-server copy/snapshot in a separate data directory for
migration validation. Preserve world and private operational settings locally;
install MODs/loader from the manifest instead of carrying old runtime binaries.
Overrides are applied at installation, so compare existing config changes.
Changing TYPE or replacing the ZIP alone does not transfer an existing world.

Check the selected image documentation for its Core API key support. If supplying your own, use
CF_API_KEY_FILE and a Docker secret (or a protected environment variable).
A Core API key is different from the author Upload API token: never put the
Upload token in this archive or on the Minecraft server. Image updates can
change installer behavior; record/pin a tested image digest for production.

References:
https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/mod-platforms/auto-curseforge/
https://blog.curseforge.com/server-packs-tutorial/
'''.encode()
    return files


def write_zip(output, files):
    release.need(not output.exists(), 'use a new server setup output')
    with output.open('xb') as handle, zipfile.ZipFile(handle,'w') as archive:
        for name, content in sorted(files.items()):
            info=zipfile.ZipInfo(name, (2000,1,1,0,0,0))
            info.create_system=3
            info.external_attr=0o100644 << 16
            # Stored entries avoid zlib/platform-dependent bytes across reruns.
            info.compress_type=zipfile.ZIP_STORED
            archive.writestr(info, content)


def verify_prepared(server, receipt, client, policy, version, refs):
    release.need(server.is_file() and not server.is_symlink() and
        server.stat().st_size <= release.MAX_ZIP, 'invalid server setup file/size')
    expected=blobs(client,policy,refs,version)
    with zipfile.ZipFile(server) as archive:
        release.need(len(archive.infolist()) == len(expected) and
                     set(archive.namelist()) == set(expected), 'unexpected server setup entries')
        for info in archive.infolist():
            release.need(info.file_size == len(expected[info.filename]) and
                not info.flag_bits & 1 and info.external_attr == 0o100644 << 16 and
                info.compress_type == zipfile.ZIP_STORED and archive.read(info) == expected[info.filename],
                'server setup bytes differ from verified inputs')
    release.need(receipt.get('schema_version')==1 and receipt.get('version')==version and
        receipt.get('client_sha256')==sha(client) and receipt.get('sha256')==sha(server) and
        receipt.get('size_bytes')==server.stat().st_size and receipt.get('filename')==server.name and
        receipt.get('format')=='manifest-installer-input', 'server receipt identity differs')
