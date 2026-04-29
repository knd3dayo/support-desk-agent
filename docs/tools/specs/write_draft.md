# write_draft

## 1. 目的

顧客向け回答やバックサポート問い合わせ文案をドラフトファイルへ出力する。

## 2. 利用エージェント

- InvestigateAgent
- BackSupportInquiryWriterAgent

## 3. 既定実装 / 接続点

- 論理ツール名: write_draft
- 既定実装: [src/support_desk_agent/tools/default_write_draft.py](/home/user/source/repos/support-desk-agent/src/support_desk_agent/tools/default_write_draft.py)
- 出力先は ToolRegistry 上の role ごとの設定に従う

## 4. 実装状況

- 区分: implemented
- 実装済み