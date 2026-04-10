# extract_text_from_file

## 1. 目的

単一ファイルからプレーンテキストを抽出し、後続の検索や解析へ渡す。

## 2. 利用エージェント

- LogAnalyzerAgent

## 3. 既定実装 / 接続点

- 論理ツール名: extract_text_from_file
- 既定実装: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- 拡張子差分を吸収して PDF / Office / テキストを同一入口で扱う

## 4. 実装状況

- 実装済み