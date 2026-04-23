# extract_zip

## 1. 目的

ZIP アーカイブを展開し、内部のログや添付証跡を後続処理可能な形へする。

## 2. 利用エージェント

- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: extract_zip
- 既定実装: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- パスワード付き ZIP は password 引数が必要になる

## 4. 実装状況

- 区分: implemented
- 実装済み