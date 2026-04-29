# extract_text_from_file

## 1. 目的

単一ファイルからプレーンテキストを抽出し、後続の検索や解析へ渡す。

## 2. 利用エージェント

- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: extract_text_from_file
- 既定実装: [src/support_desk_agent/tools/builtin_tools.py](/home/user/source/repos/support-desk-agent/src/support_desk_agent/tools/builtin_tools.py)
- 拡張子差分を吸収して PDF / Office / テキストを同一入口で扱う

## 4. 実装状況

- 区分: implemented
- 実装済み