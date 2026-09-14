# WS入賞ウォッチ — 大会データ

毎朝08:00 JST（前日23:00 UTC）と手動実行で、同じ収集・重複排除・検証・公開処理を実行します。GitHubの混雑により開始時刻が遅れることがあります。

## 手動更新

[Actions → Collect WS results](https://github.com/milkyomochi/weiss-results-data/actions/workflows/collect.yml) の **Run workflow → Run workflow** を押します。管理者のGitHubログインが必要です。サイトの「一覧を再読み込み」は表示だけの再取得です。

## データ公開

Settings → Pages → Sourceを **GitHub Actions** に設定します。
公開先は https://milkyomochi.github.io/weiss-results-data/ です。
`snapshot.json` は結果と取得状態を一体で公開します。`results.json` と `collection.json` も配信します。
不正データや既存IDの予期しない消失があれば公開を停止します。一部取得失敗の場合、検証できたデータと失敗状態は公開しますが、Actionsは失敗として終了します。

## X・優先CS検索（接続待ち）

Settings → Secrets and variables → Actions → New repository secret に `BRAVE_SEARCH_API_KEY` を追加すると検索を実行します。キーはチャットやファイルに記載しないでください。接続前は「未実行」と記録し、成功扱いにしません。

毎回、ふらめ杯・福福杯・コギナゴカップ・SSSS杯・キズナ杯を大会名とアカウントで検索します。ハリケーンCSは通常対象ですが優先対象ではありません。直近14日を検索し、検索結果からはURLだけを候補に追加します。本文で競技・成績・選手との対応を確認できたものだけ採用します。検索抜粋から日付やデッキを補完しません。全文・返信元を取得できない投稿や曖昧な結果は掲載しないため、全投稿の網羅はできません。

検索接続後は1回につき現在16検索（主催者数により変動）程度を使います。自動・手動とも同じ回数です。料金・利用上限はBrave側で確認・設定してください。
検索提供: [Brave Search API](https://brave.com/search/api/)。検索API以外にAI APIは使用しません。

ブラウ・ロゼを除外し、既存データ・出典・デッキ画像を保持します。旧Workタスクは検索接続と実行・サイト反映の確認が済むまで停止しません。

## 検証

Python 3.12で `python -X utf8 -m unittest discover -s collector` と `python -X utf8 collector/collect.py --validate-only`。
WindowsではUTF-8モードを指定してください。収集本番はGitHubのLinux環境で実行します。
