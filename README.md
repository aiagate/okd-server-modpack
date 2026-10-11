# OKD Server Modpack

Create を中心に、工場の自動化、飛行する装置づくり、素材の収納を楽しむ Minecraft の Modpack です。レシピ検索・地図・持ち物整理を助ける MOD も含みます。

**Minecraft 1.21.1 / NeoForge 21.1.250** に対応します。

## クライアント

[最新の GitHub Release](https://github.com/aiagate/okd-server-modpack/releases/latest) の Assets から、クライアント用 `okd-server-modpack-<版>.zip` をダウンロードし、CurseForge App の「Import」で読み込んで起動します。`-serverpack.zip` や GitHub の Source code ZIP はクライアント用ではありません。

## サーバー

同じ Release の `okd-server-modpack-<版>-serverpack.zip` を使います。これは `AUTO_CURSEFORGE` で MOD と NeoForge を取得するための軽量パックです。ZIP 内の `manifest.json` はクライアントと共通で、Compose の指定によりクライアント専用 MOD を除外します。MOD JAR・Java・ワールドは同梱せず、展開した JAR を直接起動する方式ではありません。

### 準備と設定

Docker Engine または Docker Desktop、Docker Compose v2、ZIP を展開できる環境、インターネット接続が必要です。Java 21 はコンテナに含まれます。ゲーム用メモリは既定で 4G なので、ホストにも余裕を確保してください。

以下は公開済み **0.0.1** の例です。新しい空の `okd-server-0.0.1` ディレクトリを作り、サーバー ZIP をそこへ置いて実行します。別の版ではディレクトリ名と ZIP 名を合わせてください。

```sh
cd okd-server-0.0.1
unzip okd-server-modpack-0.0.1-serverpack.zip
mkdir downloads
```

元 ZIP は `compose.yaml` と同じ場所に残します。ZIP 内の `manifest.json` と `SERVER-REFERENCES.json` は導入対象を記録したファイルなので編集しません。

[Minecraft EULA](https://www.minecraft.net/eula) を本人が確認し、同意する場合だけ、`compose.yaml` と同じ場所に `.env` を作成します。

```dotenv
EULA=true
MEMORY=4G
MC_PORT=25565
```

必須値は `EULA` です。`MEMORY` と `MC_PORT` は任意で、上記が既定値です。配布された `compose.yaml` の導入設定はそのまま使います。

- `TYPE=AUTO_CURSEFORGE`：manifest の固定 MOD と NeoForge を導入します。
- `CF_MODPACK_ZIP=/pack/okd-server-modpack-0.0.1-serverpack.zip`：読み取り専用でマウントした元 ZIP を指定します。ホスト側のパスや GitHub のページ URL は渡しません。
- `CF_SLUG=okd-server-modpack`：ローカル ZIP の識別子です。この方式では CurseForge の公開プロジェクトや `CF_PAGE_URL`・`CF_FILE_ID` の設定は必要ありません。

`java21` イメージにはダウンロード用の CurseForge Core API key が含まれるため、通常は自分のキーを設定せず使えます。作者用の Upload token は使いません。[インストーラーの公式案内](https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/mod-platforms/auto-curseforge/)を参照してください。

### 起動・接続・停止

同じディレクトリで実行します。

```sh
docker compose up -d
docker compose logs -f minecraft
```

ログに手動ダウンロードが必要な MOD が表示されたら、指定された版の公式ファイルをブラウザで取得して `downloads/` に置き、`docker compose restart minecraft` で再開します。起動完了後、同じパック版のクライアントから `サーバーのアドレス:MC_PORT` へ接続します。別の端末から接続する場合は、そのポートへの接続を許可する必要があります。

ワールド・設定・取得した MOD は Docker の named volume `server-data`（実際の名前には Compose プロジェクト名が付きます）に保存されます。ログ表示は Ctrl+C で終了でき、サーバーは動き続けます。サーバーを停止するには次を実行してください。

```sh
docker compose down
```

停止後も named volume のデータは残ります。`down -v` はデータを削除するため、通常の停止には使いません。既存ワールドの移行は、停止中のバックアップと構成確認を行ってから別途進めてください。詳細は ZIP 内の `README-SERVER.md` にあります。

### パックの更新

停止中にデータをバックアップし、クライアントとサーバーを同じ Release の版に揃えます。サーバー側は元の Compose プロジェクトを維持し、ZIP と `compose.yaml` を新しい版へ置き換えてください。元 ZIP のファイル名と `CF_MODPACK_ZIP` のパスが一致することを確認します。

MOD の参照が同じまま設定や除外対象だけを変更した場合は、`compose.yaml` の `minecraft.environment` に `CF_FORCE_SYNCHRONIZE: "true"` を一時的に追加して `docker compose up -d` で再作成します。適用後はその行を外し、再度 `docker compose up -d` を実行します。`docker compose restart` だけでは Compose の設定変更は反映されません。

第三者 MOD には各作者のライセンスが適用されます。

## 詳しい情報

- [変更履歴](CHANGELOG.md)
- [MOD 参照表](mods.tsv)

MIT の対象は [LICENSE](LICENSE) に記載されたスクリプト・文書・独自著作物です。
