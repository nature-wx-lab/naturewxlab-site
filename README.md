# NatureWxLab Official Site

NatureWxLab公式サイトの静的ファイルです。独自ドメイン `https://naturewxlab.com/` でのCloudflare Pages配信を前提としています。配信対象は `site/` だけです。

## Local preview

リポジトリ直下で次を実行します。

```bash
python3 -m http.server 4173 --directory site
```

ブラウザで `http://localhost:4173/` を開きます。ローカル・`pages.dev`・preview環境では、GA4の実測定IDを設定した後もGoogleタグを読み込みません。

## Analytics boundary

- 公式HP専用のGA4プロパティとウェブデータストリームを使います。
- 実測定IDを取得するまでは `assets/js/analytics-config.js` にIDを置きません。
- 仮の測定IDやAPI secretをソースへ入れません。
- 本番の `naturewxlab.com` かつ利用者が同意した場合だけGoogleタグを読み込みます。
- 広告関連の保存・シグナル・パーソナライズは常に無効です。
- 自動拡張計測はGA4管理画面で無効にし、正規化したページ閲覧と固定分類の外部リンククリックだけを送ります。
- 実測定IDを入れる前に、GA4管理画面で拡張計測の全項目がOFFであることを画面上で確認します。
- URLのquery・fragment、自由入力、氏名、メール、電話番号、住所、user IDは送信しません。

## Verification

リポジトリ直下で次を実行します。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_site.py
```

検査は `site/` のHTML・リンク・GA4安全条件・セキュリティヘッダーに加え、リポジトリ全体のローカル絶対パスと生成バイトコードを確認します。

## Publication boundary

- Cloudflare Pagesのビルド出力ディレクトリは `site` に固定し、READMEや検査スクリプトを配信しません。
- このリポジトリ以外のNatureWxLab作業データを公開対象へ含めません。
- 外部公開、GitHub repo作成、Cloudflare Pages接続、DNS変更は別の承認工程です。
- 公開前に現行ファイル、Git全履歴、Git identity、Actions log・artifact、Pages配信物をそれぞれ確認します。
- HSTSはapex・www・SSL・転送の確認後に別途判断します。
- Cloudflare Pagesのプロジェクト名は `naturewxlab-site` とし、`pages.dev` の本番・preview URLにはホスト限定の `X-Robots-Tag: noindex` を設定します。独自ドメインを一律noindexにはしません。
- 公開直前に、トップのお知らせを実際の公開日・公開文へ、ポリシー内のCloudflare表現を現在形へ更新します。
