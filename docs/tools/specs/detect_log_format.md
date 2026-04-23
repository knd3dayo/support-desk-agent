# detect_log_format

## 1. 目的

ログ形式を推定し、検索用パターンと主要一致結果を返す。

## 2. 利用エージェント

- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: detect_log_format
- 既定実装: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py) の detect_log_format_and_search
- ToolRegistry では detect_log_format_and_search を bind する

## 4. 実装状況

- 区分: implemented
- 実装済み