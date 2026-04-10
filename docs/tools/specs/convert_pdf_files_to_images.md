# convert_pdf_files_to_images

## 1. 目的

PDF をページ画像へ変換し、画像解析系ツールへ渡せる形にする。

## 2. 利用エージェント

- LogAnalyzerAgent

## 3. 既定実装 / 接続点

- 論理ツール名: convert_pdf_files_to_images
- 既定実装: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- スキャン PDF や図版中心 PDF の前処理に使う

## 4. 実装状況

- 実装済み