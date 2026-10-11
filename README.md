# OKD Server Modpack

Create を中心に、工場の自動化、飛行する装置づくり、素材の収納を楽しむ Minecraft の Modpack です。レシピ検索・地図・持ち物整理を助ける MOD も含みます。

**Minecraft 1.21.1 / NeoForge 21.1.250** に対応します。

## 遊び方・サーバー導入

[0.0.1 のダウンロード](https://github.com/aiagate/okd-server-modpack/releases/tag/v0.0.1)から、クライアント用 `okd-server-modpack-0.0.1.zip` を CurseForge App にインポートしてください。CurseForge での公開は準備中です。

### サーバー

サーバー用 `okd-server-modpack-0.0.1-serverpack.zip` は、Docker の標準インストーラーに渡す軽量の導入パックです。MOD JAR・Java・ワールドは同梱しません。

空のディレクトリへ展開し、元 ZIP を `compose.yaml` と同じ場所に残してください。Minecraft EULA を確認し、同意する場合だけ次を実行します。初回は既存ワールドと異なる新しい volume を使います。

```sh
mkdir downloads
EULA=true docker compose up -d
docker compose logs -f
```

自動取得できない MOD は、ZIP 内の指定 file ID の公式ファイルを取得して `downloads/` に置きます。ログを確認し、同じ版のクライアントで接続してください。詳しい導入案内は ZIP 内の `README-SERVER.md` にあります。既存ワールドを移行する場合は、先にバックアップと構成確認を行ってください。

初版は公開取込プレビューの構成を引き継いでいます。稼働中サーバーの最新設定を完全に再現したものではなく、今回の配布 ZIP のゲーム・専用サーバー起動は未検証です。第三者 MOD には各作者のライセンスが適用されます。

## 詳しい情報

- [変更履歴](CHANGELOG.md)
- [MOD 参照表](mods.tsv)

MIT の対象は [LICENSE](LICENSE) に記載されたスクリプト・文書・独自著作物です。
