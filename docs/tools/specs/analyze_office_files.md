# analyze_office_files

## 1. 目的

Excel、Word、PowerPoint などの Office 添付から文字情報を抽出し、調査観点に応じて解析する。

## 2. 利用エージェント

- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: analyze_office_files
- 既定実装: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- Excel 内のエラー一覧や時系列表の読解を想定する

## 4. 実装状況

- 区分: implemented
- 実装済み