# 公開手順

GitHub Release と CurseForge の審査・公開は別々に判定します。OKD の CurseForge project は現在未確定です。2026-10-11、Fedora のユーザー Chrome の作者 aiagate の一覧には Shimae の1件だけがありました。Shimae project へは提出しません。

## CurseForge 公開の前提

本人が OKD project と必要な公開説明・画像を確定し、実際の project ID を `pack/release.json` に設定します。新 token の設定、永続権限・保護設定、規約への新しい明示同意は本作業で自動実施しません。

提出には `curseforge` Environment の required reviewers、secret `CURSEFORGE_API_TOKEN`、variable `CURSEFORGE_SUBMISSION_ENABLED=true` が必要です。既存承認を迂回しません。対象未設定・承認ルールなし・取得不能なら実提出は停止します。現状は repository Secret と Environment の一覧が空です。

## 承認から公開照合

1. PR を draft で作り、最終 commit の CI、ZIP、receipt を確認して main へマージ。
2. main の **Release / Submit** を起動。`submit=false` はオフライン検証です。実提出 run は preflight の同 run artifact ID、source SHA、両 ZIP SHA を保存。
3. 内容レビュー後、本人が既存の `curseforge` deployment を承認。提出 job は成果物を再ビルドせずに使用。
4. 読み取り API audit 後、タグ `v<version>` と検証済み ZIP を GitHub Release へ保存。既存同名 asset は SHA・サイズ一致時だけ再利用し、上書きしない。
5. POST 前 claim と受付後 result を Release に保存。結果があるファイルは再送しない。claim のみなら別 run も停止し、作者画面と receipt で受付を確認。client ID を server の `parentFileID` とし、`isServerPack:true` を送る。
6. **Release / Verify publication** で両 Approved、実 Server Pack 区分、親子関係、CDN の全 ZIP SHA を照合。`publication_complete:true` のみを公開完了とする。

`isServerPack` は Upload API の未文書化フィールドです。受付 ID から実分類を推測しません。区分未設定・曖昧なら同じ受付済みファイルの作者画面を確認し、必要な Server Pack 設定を保存します。再アップロードはしません。審査待ちは読み取り検証だけを継続します。

GitHub のみ先行公開した ZIP も source commit と SHA を保持します。CurseForge 対象設定など正本が変わる場合は、既存版の配布物を黙って作り直して上書きせず、新しい版で通常のレビューを行います。CI 成功、GitHub 公開、CurseForge API 受付は審査 Approved の代わりにはなりません。
