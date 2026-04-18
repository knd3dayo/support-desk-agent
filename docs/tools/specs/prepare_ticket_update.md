# prepare_ticket_update

## 1. 目的

draft_response をもとに外部チケット更新用ペイロードを構成する。

## 2. 利用エージェント

- TicketUpdateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: prepare_ticket_update
- builtin 既定実装: `build_default_prepare_ticket_update_tool`
- TicketUpdateAgent は lookup 済み ticket summary や follow-up question をこの tool へ渡して payload を構成する

## 4. 実装状況

- 実装済み