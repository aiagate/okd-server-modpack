# 開発・ビルド手順

## 移行元と公開履歴

既存の public リポジトリ `minecraft-modpack-release` を `okd-server-modpack` に改名し、履歴と旧配布物を保持しました。公開取込プレビュー `e7e0fbd0e7dc405d21e8bb44fe4282a3651ac15a` の固定参照20件を初版へ引き継ぎ、Inventory Profiles Next (495267) と libIPN (679177) のみをサーバーから除外しています。独自 config、world、接続先、認証情報は含みません。Shimae の MOD・サーバー設定・提出対象は取り込みません。

旧タグ `okd-server-modpack-import-preview-20261006-e7e0fbd` と `preview-create-client-20261006-9f7671a` は保存しています。仮版 `0.0.0-local.20260913` は正式提出用に使いません。

v0.0.1 の配布元は commit `644310d32881816f66949f1cedf67df946060585`、[main CI](https://github.com/aiagate/okd-server-modpack/actions/runs/38136604456) の artifact `11701660419` です。当時の80テスト、両 ZIP の静的検証、独立再ビルドの内容一致、取得 artifact digest を確認し、再ビルドせず公開しました。ZIP SHA と詳しい記録は Release 添付の `.sha256` と `github-release-receipt.json`、client/server/plan receipt を参照してください。GitHub の Source code ZIP はクライアント取込用ではありません。

元の参照構成には Windows の取込・起動・サーバー参加成功のユーザー報告がありますが、新しい配布 ZIP の実機検証とは区別します。OKD の CurseForge project は未確定で、提出・審査 Approved・実 Server Pack 区分・親子関係・公開 ZIP SHA は未確認です。

提出の再開には公開済み両 ZIP と source receipt を asset ID・tag commit・SHA で照合する経路を使います。新 dispatch と server_only 復旧でも再ビルドしません。対象設定や版を変更する場合は新しい版でレビューし、v0.0.1 の公開ファイルは置き換えません。

## ビルド

正本は `pack/release.json`、`pack/client.refs.json`、`pack/server.refs.json`、`pack/overrides/` です。MOD 更新は project ID / file ID を明示してレビューします。自動更新・依存の自動追加はしません。

初版 `0.0.1` は既存に通常版タグがないため選びました。`pack/migration.json` は公開プレビュー e7e0fbd を出所として初版の参照・配布文書 SHA を固定します。App 原本や実機最新構成への移行を示す記録ではありません。配布 author はリポジトリ所有者 `aiagate` で、実名を推定しません。

Go 1.27.2 / packwiz `v0.0.0-20260218225342-dfd8b68a4796` を使用し、コンパイラー・module checksum を照合します。固定参照から一時 packwiz メタデータを作り、標準 exporter に生成させます。生成後の manifest は編集せず、entry 本文を保持して ZIP の順序・時刻・属性を揃えます。Go map の列挙順序により ZIP SHA の再ビルド一致は保証しないため、参照・設定の意味的な内容一致と同 run の実ファイル SHA を照合します。

```sh
python3 -m unittest discover -s tests -v
GOBIN=/tmp/okd-tools go install github.com/packwiz/packwiz@v0.0.0-20260218225342-dfd8b68a4796
python3 scripts/native_pack.py --output /tmp/okd-build --packwiz /tmp/okd-tools/packwiz
python3 scripts/publish_pair.py --client /tmp/okd-build/okd-server-modpack-0.0.1.zip --client-receipt /tmp/okd-build/client.json --server /tmp/okd-build/okd-server-modpack-0.0.1-serverpack.zip --server-receipt /tmp/okd-build/server.json --receipt /tmp/okd-build/plan.json
```

新ビルドの source commit receipt を追加するには `python3 scripts/published_pack.py --output /tmp/okd-build --record-build` を実行します。CI はこれを自動実行します。公開済み ZIP の読み取り取得は `python3 scripts/published_pack.py --output /tmp/okd-saved-release` です。checkout は元のタグ commit を含む履歴が必要です。

出力先は未作成のディレクトリを使います。通常は CI / Validate がテスト、固定ツール、両 ZIP の検証、独立再ビルド比較、artifact 保存を行います。MOD JAR、ZIP、world、私的資料を Git に追加しません。`project_id: null` は対象未確定を表し、オフラインビルドのみ可能です。実提出は未設定の対象を拒否します。
