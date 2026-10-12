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
    files['README-SERVER.md'] = f'''# OKD Server Modpack {version}: サーバー導入

`manifest.json` に記録された MOD と NeoForge を、Docker の標準
`AUTO_CURSEFORGE` インストーラーで取得するための軽量パックです。
MOD JAR・Java・ワールド・認証情報・EULA への同意は同梱しません。
`manifest.json` はクライアントと共通で、`SERVER-REFERENCES.json` と
`compose.yaml` の指定によりクライアント専用 MOD を除外します。

## 準備と設定

Docker Engine または Docker Desktop、Docker Compose v2、ZIP を展開できる
環境、インターネット接続が必要です。Java 21 はコンテナに含まれます。
ゲーム用メモリは既定で 4G なので、ホストにも余裕を確保してください。

新しい空の `okd-server-{version}` ディレクトリを作り、`{name}` を置いて実行します。

```sh
cd okd-server-{version}
unzip {name}
mkdir downloads
```

元 ZIP は `compose.yaml` と同じ場所に残し、`manifest.json` と
`SERVER-REFERENCES.json` は編集しません。Minecraft EULA を本人が確認し、
同意する場合だけ、同じ場所に `.env` を作成します。

```dotenv
EULA=true
MEMORY=4G
MC_PORT=25565
```

必須値は `EULA` です。`MEMORY` と `MC_PORT` は任意で、上記が既定値です。
配布された `compose.yaml` の導入設定はそのまま使います。

- `TYPE=AUTO_CURSEFORGE`：manifest の固定 MOD と NeoForge を導入します。
- `CF_MODPACK_ZIP=/pack/{name}`：読み取り専用でマウントした元 ZIP を指定します。
- `CF_SLUG=okd-server-modpack`：ローカル ZIP の識別子です。この方式では
  CurseForge の公開プロジェクトや `CF_PAGE_URL`・`CF_FILE_ID` は必要ありません。

`java21` イメージにはダウンロード用の CurseForge Core API key が含まれるため、
通常は自分のキーを設定せず使えます。作者用の Upload token は使いません。
自分の Core API key を使う場合は `CF_API_KEY_FILE` と Docker secret などで保護します。

## 起動・接続・停止

同じディレクトリで実行します。

```sh
docker compose up -d
docker compose logs -f minecraft
```

ログに手動ダウンロードが必要な MOD が表示されたら、指定された版の公式ファイルを
ブラウザで取得して `downloads/` に置き、`docker compose restart minecraft` で再開します。
起動完了後、同じパック版のクライアントから `サーバーのアドレス:MC_PORT` へ接続します。
別の端末から接続する場合は、そのポートへの接続を許可してください。

ワールド・設定・取得した MOD は Compose プロジェクトの named volume
`server-data` に保存されます。ログ表示は Ctrl+C で終了でき、サーバーは動き続けます。
`docker compose down` で停止してもデータは残ります。`down -v` はデータを削除するため、
通常の停止には使いません。

## パックの更新

停止中にデータをバックアップし、クライアントとサーバーを同じ Release の版に揃えます。
元の Compose プロジェクトを維持して ZIP と `compose.yaml` を新しい版へ置き換え、
元 ZIP のファイル名と `CF_MODPACK_ZIP` のパスが一致することを確認してください。

MOD の参照が同じまま設定や除外対象だけを変更した場合は、`minecraft.environment` に
`CF_FORCE_SYNCHRONIZE: "true"` を一時的に追加し、`docker compose up -d` で再作成します。
適用後はその行を外し、再度 `docker compose up -d` を実行します。
`docker compose restart` だけでは Compose の設定変更は反映されません。

既存ワールドの移行は別途行います。旧 `CURSEFORGE` は既定で `/data/FeedTheBeast`、
`AUTO_CURSEFORGE` は `/data` を使用するため、実際の作業ディレクトリと `level-name` を
確認し、停止中のコピーまたはスナップショットを別のデータ領域で検証してください。
ワールドと運用設定は手元で保持し、MOD と loader は manifest から導入します。
既存 config の変更も比較してください。TYPE や ZIP の変更だけではワールドは移りません。

TrueNAS では、同じ読み取り専用の pack/downloads マウントと、新しい `/data` dataset を
使う別の Custom App でも導入できます。本番では検証したイメージの digest を固定してください。

Minecraft EULA: https://www.minecraft.net/eula
インストーラーの公式案内:
https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/mod-platforms/auto-curseforge/
導入案内: https://github.com/aiagate/okd-server-modpack/blob/main/README.md#サーバー
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
