# LogAnalyzerAgent 用ツール設計

## 1. 対象ツール

- detect_log_format
- read_log_file
- run_python_analysis

## 2. 共通ツール参照

- working memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- detect_log_format: ログ形式を推定し、検索用パターンと主要一致結果を返す。既定実装は [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py) の detect_log_format_and_search を利用する。
- read_log_file: 対象ログ本文を読む
- run_python_analysis: Python ベースの追加解析を行う

## 4. 実装状況

- detect_log_format: 実装済み
- read_log_file: 未実装
- run_python_analysis: 未実装
- write_working_memory: 共通ツールとして未実装