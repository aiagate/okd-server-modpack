# OKD Server Modpack

Create を中心に、工場の自動化、飛行する装置づくり、素材の収納を楽しむ Minecraft の Modpack です。レシピ検索・地図・持ち物整理を助ける MOD も含みます。

**Minecraft 1.21.1 / NeoForge 21.1.250** に対応します。

## クライアント

[最新の GitHub Release](https://github.com/aiagate/okd-server-modpack/releases/latest) の Assets から、クライアント用 `okd-server-modpack-<版>.zip` をダウンロードし、CurseForge App の「Import」で読み込んで起動します。`-serverpack.zip` や GitHub の Source code ZIP はクライアント用ではありません。

## サーバー

同じ Release の `okd-server-modpack-<版>-serverpack.zip` を使います。これは Docker の標準インストーラーで MOD と NeoForge を取得するための軽量パックです。MOD JAR・Java・ワールドは同梱せず、展開した JAR を直接起動する方式ではありません。

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

必須値は `EULA` です。`MEMORY` と `MC_PORT` は任意で、上記が既定値です。配布された `compose.yaml` の `TYPE=AUTO_CURSEFORGE` と `CF_MODPACK_ZIP=/pack/okd-server-modpack-0.0.1-serverpack.zip` はそのまま使います。[インストーラーの公式案内](https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/mod-platforms/auto-curseforge/)も参照してください。

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

第三者 MOD には各作者のライセンスが適用されます。

## 詳しい情報

- [変更履歴](CHANGELOG.md)
- [MOD 参照表](mods.tsv)

MIT の対象は [LICENSE](LICENSE) に記載されたスクリプト・文書・独自著作物です。
