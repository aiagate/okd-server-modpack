# OKD Server Modpack

Minecraft **1.21.1 / NeoForge 21.1.250** 向けの Modpack です。固定 MOD 参照20件のクライアント ZIP と、クライアント専用2件を除く18件の軽量サーバーパックを配布します。

## ダウンロード

初版 [0.0.1](https://github.com/aiagate/okd-server-modpack/releases/tag/v0.0.1) のクライアントは `okd-server-modpack-0.0.1.zip`、サーバー導入用は `okd-server-modpack-0.0.1-serverpack.zip` です。公開状況と SHA256 は Release の実ファイル・receipt を確認してください。

クライアント ZIP を CurseForge App にインポートすると、指定 MOD が取得されます。サーバー ZIP は MOD JAR や Java を含む完成済みサーバーではありません。Docker の標準インストーラーへ渡す導入資料です。[サーバー導入手順](docs/server-setup.md)を参照してください。

## 構成の出所と検証範囲

正本は `pack/` の固定参照と配布文書です。初版は公開取込プレビュー `e7e0fbd0e7dc405d21e8bb44fe4282a3651ac15a` の20件を保持しています。実環境の完全な最新構成を取得したものではありません。独自 config、world、接続先、認証情報は含めません。

Inventory Profiles Next (`495267`) と libIPN (`679177`) はクライアント専用としてサーバーから除外します。その他の file ID、Minecraft、NeoForge は変更していません。[MOD 参照表](docs/mods.tsv)に出所と当時の Environment・ライセンス表示を保存しています。

元の参照構成について Windows の取込・起動・サーバー参加成功のユーザー報告があります。今回の生成 ZIP と専用サーバーの実機起動は CI の静的検証範囲外です。CurseForge の OKD project は未確定で、CurseForge 提出・審査 Approved・Server Pack 区分は未確認です。GitHub Release の公開を CurseForge 審査完了と扱いません。

## 開発と公開

- [開発手順](docs/development.md)：正本、固定 exporter、テスト、ビルドと CI。
- [公開手順](docs/publishing.md)：対象設定、承認、正確な artifact、二重提出防止と公開照合。
- [変更履歴](CHANGELOG.md)：初版の内容と旧プレビューの保全。

既存 `minecraft-modpack-release` を public のまま改名しました。旧タグと Release assets は履歴として残しています。Shimae の設定・MOD・提出対象は取り込みません。検証・提出プログラムは Shimae の MIT ライセンスの実装を OKD 用に適用し、元の著作権表示を保持しています。
