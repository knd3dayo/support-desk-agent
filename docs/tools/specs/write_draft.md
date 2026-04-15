# write_draft

## 1. 目的

顧客向け回答やバックサポート問い合わせ文案をドラフトファイルへ出力する。

## 2. 利用エージェント

- InvestigateAgent
- BackSupportInquiryWriterAgent

## 3. 既定実装 / 接続点

- 論理ツール名: write_draft
- 既定実装: [src/support_ope_agents/tools/default_write_draft.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_write_draft.py)
- 出力先は ToolRegistry 上の role ごとの設定に従う

## 4. 実装状況

- 実装済み