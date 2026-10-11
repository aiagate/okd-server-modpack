# 開発・ビルド手順

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
