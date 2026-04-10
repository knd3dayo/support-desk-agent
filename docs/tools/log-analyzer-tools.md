# LogAnalyzerAgent 用ツール設計

## 1. 対象ツール

- analyze_pdf_files
- analyze_office_files
- analyze_image_files
- extract_text_from_file
- list_zip_contents
- extract_zip
- convert_pdf_files_to_images
- detect_log_format
- read_log_file
- run_python_analysis

## 2. 共通ツール参照

- working memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- analyze_pdf_files: PDF 化されたログ、帳票、調査資料から文字情報を抽出して解析する。ログ本文が PDF 添付で渡されるケースを想定する。
- analyze_office_files: Excel / Word / PowerPoint などの調査添付から文字情報を抽出して解析する。Excel 内のエラー一覧や時系列表の読み取りを想定する。
- analyze_image_files: スクリーンショットや監視画面画像を解析する。エラーダイアログ、UI 上のメッセージ、グラフ異常の確認を想定する。
- extract_text_from_file: プレーンテキスト抽出の共通入口。拡張子依存の差を吸収して detect_log_format や追加解析へ渡す前処理に使う。
- list_zip_contents: ZIP 添付の中身を確認する。複数ログや補助証跡がまとめて渡されるケースで利用する。
- extract_zip: ZIP を作業ディレクトリへ展開する。展開後にログ / PDF / Excel / 画像を再帰的に処理する。
- convert_pdf_files_to_images: スキャン PDF や図版中心 PDF を画像へ変換し、analyze_image_files に渡す前処理に使う。
- detect_log_format: ログ形式を推定し、検索用パターンと主要一致結果を返す。既定実装は [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py) の detect_log_format_and_search を利用する。
- read_log_file: 対象ログ本文を読む
- run_python_analysis: Python ベースの追加解析を行う

## 4. 実装状況

- analyze_pdf_files: 実装済み
- analyze_office_files: 実装済み
- analyze_image_files: 実装済み
- extract_text_from_file: 実装済み
- list_zip_contents: 実装済み
- extract_zip: 実装済み
- convert_pdf_files_to_images: 実装済み
- detect_log_format: 実装済み
- read_log_file: 未実装
- run_python_analysis: 未実装
- write_working_memory: 共通ツールとして未実装