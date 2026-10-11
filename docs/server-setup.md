# サーバー導入手順

同じ版の `okd-server-modpack-<version>-serverpack.zip` を空のディレクトリに置き、そこへ展開します。元 ZIP を `compose.yaml` と同じディレクトリに残し、空の `downloads/` を作ります。ZIP に MOD JAR・Java・world・認証情報・EULA 同意は含めません。

Minecraft EULA を本人が確認し、同意する場合だけ `EULA=true` を明示して Docker Compose を実行します。初回は既存本番 world と異なる新しい volume を使用します。

```sh
mkdir downloads
EULA=true docker compose up -d
docker compose logs -f
```

標準 itzg AUTO_CURSEFORGE が ZIP 内の固定 manifest と NeoForge を取得します。Inventory Profiles Next と libIPN を除き、サーバー用18参照を指定します。自動取得できない MOD は指定 file ID の公式配布ファイルを本人が取得し `downloads/` に置きます。最新版へ置換しません。

ログを確認し、対応する同版クライアントで接続します。実機起動・全依存グラフ・移行互換性は静的検査では保証しません。既存 world の移行には別途バックアップと構成照合が必要です。`SERVER-REFERENCES.json` は参照の一覧、`README-SERVER.md` は生成版の導入説明です。
