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
- 実測定IDは `assets/js/analytics-config.js` の1箇所だけに置きます。
- 仮の測定IDやAPI secretをソースへ入れません。
- 本番の `naturewxlab.com` かつ利用者が同意した場合だけGoogleタグを読み込みます。
- 広告関連の保存・シグナル・パーソナライズは常に無効です。
- 自動拡張計測はGA4管理画面で無効にし、正規化したページ閲覧と固定分類の外部リンククリックだけを送ります。
- 実測定IDを入れる前に、GA4管理画面で拡張計測の全項目がOFFであることを画面上で確認します。
- URLのquery・fragment、自由入力、氏名、メール、電話番号、住所、user IDは送信しません。

## Verification

リポジトリ直下で次を実行します。

GA4管理画面で確認した公式HP専用の測定IDを、検査時だけ環境変数へ渡します。

```bash
NATUREWXLAB_GA4_ID='専用測定ID' PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_site.py
```

検査は `site/` のHTML・リンク・GA4安全条件・セキュリティヘッダーに加え、リポジトリ全体のローカル絶対パスと生成バイトコードを確認します。

## Editorial imagery

ユーザー指定の横長画像を3か所だけに使用します。画像はPUBLIC TOOLSの見出し・説明・カードと同じ最大1120pxのコンテンツ幅に揃え、PCでも画像だけが過度に主張しない横長バナーとして表示します。画像下の説明注釈は表示せず、内容を伝えるaltだけを付けます。外部画像URLは読み込まず、すべてローカル配信します。サイトの説明用ビジュアルとして扱い、NatureWxLabの実在する研究施設、庭、飼育環境を記録した写真とは位置づけません。

- `editorial-rose-garden-banner-20260716.jpg`：日差しの中でバラが咲く庭園。HomeのOUR APPROACH末尾に掲載。2172×724 JPEG。
- `editorial-medaka-pond-banner-20260716.jpg`：緑に囲まれた池を泳ぐメダカ。AboutのORIGINに掲載。2048×626 JPEG。
- `editorial-summer-sky-banner-20260716.jpg`：強い日差しと青空・白い雲。VisionのNOW説明後に掲載。2048×626 JPEG。

公開用JPEGは、各元画像の構図と縦横比を切り抜かず保ったまま最適化します。画像枠は `width: 100%; max-width: var(--content)` とし、各ページの `.section-inner` と同じ基準線へ揃えます。寸法・形式・SHA-256・許可する最小限の画像メタデータを検査スクリプトで固定します。Toolsは既存の初期画面画像を優先し、Policyは可読性と説明責任を優先して装飾写真を追加しません。

## Vision roadmap

VisionのFUTUREは、地道な情報発信、信頼されるブランド、リアルな体験、リアルとオンラインを結ぶ「自然の街」へ向かう01〜04の道のりとして示します。オンライン上の街では、アバターを通じた情報共有、植物やメダカの紹介、適切な仕組みのもとでの交換・販売と、リアルなイベントや店舗との往来を構想します。04だけを控えめに強調し、支援・収益を次の活動へ還元する `CONTINUITY` は第5段階に見えない独立セクションのまま、左側のタイムライン位置を保ちながらFUTURE／PROMISEと同じ右端まで使い、同じ線色・淡いグラデーションを使う締めのパネルとして配置します。現在地と構想を分けて伝える `PROMISE` と公開ツールへの導線は維持します。

この更新では既存の青空画像をそのまま使用します。検討中の構想イラストは、内容とモバイル表示を見直してから別の更新で扱うため、公開ファイルと画像allowlistには追加しません。NOW左列はPCで14pxだけ上げ、見える書き出し位置を右側カードの上端に揃えます。NOWタイトルはPCで1行表示とし、880px以下では位置補正とnowrapを解除して自然な一段組みに戻します。FUTUREの見出しと01〜04タイムライン、CONTINUITYの右端はNOW／PROMISEと同じコンテンツ幅を使用します。HOW TO CHOOSE導入文は前半2文と後半2文の2段落とし、1160px以上では各段落を1行で表示します。全ページのCSS参照は `v=20260722-1` です。

FUTURE導入文は「地道な情報発信から、頼られるブランドへ。」の直後で改行し、続く将来像を次の行から読める構成にします。文言は変更せず、この改行位置を公開前検査で固定します。

01は天気・植物・園芸・農業・メダカなどをテーマに、暮らしや判断に役立つ記事・動画・無料ツールを届ける方針とし、その文の直後で改行します。02はブランドを「判断のよりどころ」にできる表現を維持します。03は自ら企画・主催するイベントからNatureWxLab店舗と日常的なリアル交流拠点へ育てる構想、04はリアルな場からオンライン上の「自然の街」へ広げる冒頭2文を同じ段落で続け、経験と知恵が双方を行き来する構想を示します。CONTINUITY末文は本文と同じ16pxを保ち、「NatureWxLab全体が」を入れず、1160px以上で1行表示します。狭幅では自然に折り返します。

## Mobile navigation and layout

- 880px以下では、常時表示していたナビを「ロゴ＋メニューボタン」のコンパクトなヘッダーへ切り替えます。
- メニューは外側のタップ、リンク選択、Escapeキー、PC幅への復帰で閉じます。開閉状態は `aria-expanded` とラベルにも反映します。
- JavaScriptを利用できない場合はナビを隠さず、通常のリンク一覧として表示します。
- 560px以下では、本文の手動改行を減らし、セクション余白とカード内余白を狭めます。PC用の基準幅と見出し構成は変更しません。

## Social brand assets

トップの媒体カードでは、各サービスを識別する目的に限ってローカル保存したブランドマークを使用します。外部CDNや各サービスの画像URLは読み込まないため、アイコン表示だけで第三者への通信は発生しません。

- note：公式の[ブランドガイドライン](https://www.help-note.com/hc/ja/articles/360000235582-%E3%83%96%E3%83%A9%E3%83%B3%E3%83%89%E3%82%AC%E3%82%A4%E3%83%89%E3%83%A9%E3%82%A4%E3%83%B3-%E3%83%AD%E3%82%B4%E3%83%87%E3%83%BC%E3%82%BF-%E3%82%AB%E3%83%A9%E3%83%BC)で案内される小サイズ向けの角丸 `n` アイコン。画像自体は加工せず、サイト内では他媒体と共通の42×42px角丸枠へ収める
- X：公式の[ブランドツールキット](https://about.x.com/ja/who-we-are/brand-toolkit)で配布されるXロゴ
- Instagram：Meta公式の[Instagramブランドリソース](https://about.meta.com/brand/resources/instagram/instagram-brand/)で配布される黒色グリフ
- YouTube：公式の[YouTubeブランドリソース](https://brand.youtube/youtube-icon/)で使用されている小型ソーシャルリンク用のYouTube Redマーク
- メルカリ：公式の[ロゴ・アイコン利用規約](https://about.mercari.com/logo-terms/)に従い、[公式プレスキット](https://about.mercari.com/press/press-kit/mercari/)配布のサービスアイコンを無加工で使用

Yahoo!オークションの公式ロゴ・サービスアイコンは、LINEヤフーの[ブランド資産利用ガイドライン](https://www.lycorp.co.jp/ja/company/trademarks/)上、事前承諾なしでは使用しません。現在は公式配布資産ではなく、黄色背景に太い黒字で `ヤフオク!` と組んだサイト内テキスト表現と正式サービス名で識別します。

各ブランドマークの権利はそれぞれの権利者に帰属します。リンク先の識別以外には使用せず、提携・承認を示すものではありません。

## Publication boundary

- Cloudflare Pagesのビルド出力ディレクトリは `site` に固定し、READMEや検査スクリプトを配信しません。
- このリポジトリ以外のNatureWxLab作業データを公開対象へ含めません。
- 外部公開、GitHub repo作成、Cloudflare Pages接続、DNS変更は別の承認工程です。
- 公開前に現行ファイル、Git全履歴、Git identity、Actions log・artifact、Pages配信物をそれぞれ確認します。
- HSTSはapex・www・SSL・転送の確認後に別途判断します。
- Cloudflare Pagesのプロジェクト名は `naturewxlab-site` とし、`pages.dev` の本番・preview URLにはホスト限定の `X-Robots-Tag: noindex` を設定します。独自ドメインを一律noindexにはしません。
- トップのお知らせは実際の公開日・公開文、ポリシー内のCloudflare表現は現在形へ更新済みです。
