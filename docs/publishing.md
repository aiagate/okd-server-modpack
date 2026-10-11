# 公開手順

GitHub Release と CurseForge の審査・公開は別々に判定します。OKD の CurseForge project は現在未確定です。2026-10-11、Fedora のユーザー Chrome の作者 aiagate の一覧には Shimae の1件だけがありました。Shimae project へは提出しません。

## CurseForge 公開の前提

本人が OKD project と必要な公開説明・画像を確定し、実際の project ID を `pack/release.json` に設定します。新 token の設定、永続権限・保護設定、規約への新しい明示同意は本作業で自動実施しません。

提出には `curseforge` Environment の required reviewers、secret `CURSEFORGE_API_TOKEN`、variable `CURSEFORGE_SUBMISSION_ENABLED=true` が必要です。既存承認を迂回しません。対象未設定・承認ルールなし・取得不能なら実提出は停止します。現状は repository Secret と Environment の一覧が空です。

## 承認から公開照合

1. PR を draft で作り、最終 commit の CI、ZIP、receipt を確認して main へマージ。
2. main の **Release / Submit** を起動。初回の新しい版は `artifact_source=new_build`、公開済み版の再開・`server_only` 復旧は既定の `published_release` を使います。`submit=false` は提出しない検証です。公開版取得モードは GitHub の読み取り通信だけを行います。実提出 run は preflight の同 run artifact ID、source commit、source SHA、両 ZIP SHA を保存。
3. 内容レビュー後、本人が既存の `curseforge` deployment を承認。提出 job は成果物を再ビルドせずに使用。
4. 読み取り API audit 後、タグ `v<version>` と検証済み ZIP を GitHub Release へ保存。既存同名 asset は SHA・サイズ一致時だけ再利用し、上書きしない。
5. POST 前 claim と受付後 result を Release に保存。結果があるファイルは再送しない。claim のみなら別 run も停止し、作者画面と receipt で受付を確認。client ID を server の `parentFileID` とし、`isServerPack:true` を送る。
6. **Release / Verify publication** で両 Approved、実 Server Pack 区分、親子関係、CDN の全 ZIP SHA を照合。`publication_complete:true` のみを公開完了とする。

`isServerPack` は Upload API の未文書化フィールドです。受付 ID から実分類を推測しません。区分未設定・曖昧なら同じ受付済みファイルの作者画面を確認し、必要な Server Pack 設定を保存します。再アップロードはしません。審査待ちは読み取り検証だけを継続します。

GitHub のみ先行公開した ZIP も source commit と SHA を保持します。CurseForge 対象設定など正本が変わる場合は、既存版の配布物を黙って作り直して上書きせず、新しい版で通常のレビューを行います。CI 成功、GitHub 公開、CurseForge API 受付は審査 Approved の代わりにはなりません。


## 保存したバイト列で再開する

`published_release` は現在の `pack/release.json` の版に対応する公開タグを選び、両 ZIP・client/server receipt・`github-release-receipt.json` を asset ID から取得します。全ダウンロードのサイズと GitHub digest を照合し、タグが示す正確な source commit が現行 checkout の祖先であること、その commit の `pack/` と現行正本が一致することを確認します。過去 commit のプログラムは実行しません。ZIP の source SHA、参照、設定、manifest、receipt を再検証します。

取得した元 receipt は書き換えず、別の `acquisition.json` に選択 Release ID と取得 asset ID/digest を記録します。承認後の job は同 run の artifact ID を固定し、公開タグ・元 receipt・両 ZIP digest を再照合します。再ビルドの fallback はありません。

新しい版の `new_build` は同版の既存 Release があると preflight で停止します。承認後に GitHub へ両 ZIP と3つの source/ZIP receipt を上書きせず保存してから、永続 claim/result による提出を行います。これにより、新 dispatch の `server_only` 復旧も元の公開 ZIP を使えます。claim のみの受付不明状態をこの経路で解除することはありません。

現在の `v0.0.1` は対象未確定の GitHub 公開版です。対象設定後は新しい版で通常レビュー・初回 `new_build` を行い、`v0.0.1` を無理に再結合したり差し替えたりしません。
