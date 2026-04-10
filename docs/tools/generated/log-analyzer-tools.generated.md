# LogAnalyzerAgent ツール下書き

このファイルは ToolRegistry から半自動生成した下書きです。

## 共通ツール
- analyze_image_files: Analyze local image files (provider=builtin, target=analyze_image_files, status=implemented, override=allowed)
- analyze_pdf_files: Analyze local PDF files (provider=builtin, target=analyze_pdf_files, status=implemented, override=allowed)
- analyze_office_files: Analyze local Office files (provider=builtin, target=analyze_office_files, status=implemented, override=allowed)
- convert_office_files_to_pdf: Convert Office files to PDF (provider=builtin, target=convert_office_files_to_pdf, status=implemented, override=allowed)
- convert_pdf_files_to_images: Convert PDF files to page images (provider=builtin, target=convert_pdf_files_to_images, status=implemented, override=allowed)
- analyze_image_urls: Analyze image URLs (provider=builtin, target=analyze_image_urls, status=implemented, override=allowed)
- analyze_pdf_urls: Analyze PDF URLs (provider=builtin, target=analyze_pdf_urls, status=implemented, override=allowed)
- analyze_office_urls: Analyze Office URLs (provider=builtin, target=analyze_office_urls, status=implemented, override=allowed)
- extract_text_from_file: Extract text from a local file (provider=builtin, target=extract_text_from_file, status=implemented, override=allowed)
- extract_base64_to_text: Extract text from base64-encoded file content (provider=builtin, target=extract_base64_to_text, status=implemented, override=allowed)
- list_zip_contents: List ZIP archive contents (provider=builtin, target=list_zip_contents, status=implemented, override=allowed)
- extract_zip: Extract ZIP archive (provider=builtin, target=extract_zip, status=implemented, override=allowed)
- create_zip: Create ZIP archive (provider=builtin, target=create_zip, status=implemented, override=allowed)
- detect_log_format_and_search: Detect log format from the first lines, generate regex patterns, and search the log (provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed)
- write_working_memory: Write agent working memory (provider=builtin, target=default-working-memory-writer, status=implemented, override=allowed)

## role 固有ツール
- read_log_file: Read attached log file (provider=local, target=n/a, status=planned, override=allowed)
- detect_log_format: Detect log format and generate regex-based search results (provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed)
- run_python_analysis: Run code-based log analysis (provider=local, target=n/a, status=planned, override=allowed)

## 手編集メモ
- ここに入出力例、運用上の注意、MCP 接続前提などを追記する。
- 既存の docs/tools/*.md を置き換えるのではなく、レビュー用の下書きとして使う。
