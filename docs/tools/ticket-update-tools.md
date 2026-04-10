# TicketUpdateAgent 用ツール設計

## 1. 対象ツール

- prepare_ticket_update
- zendesk_reply
- redmine_update

## 2. 共通ツール参照

- 特になし

## 3. role 固有ツール

- prepare_ticket_update: draft_response をもとに外部更新用ペイロードを構成する
- zendesk_reply: Zendesk への返信またはチケット更新を実行する
- redmine_update: Redmine へのコメント追加やステータス更新を実行する

## 4. 実装状況

- prepare_ticket_update: 未実装
- zendesk_reply: 未実装
- redmine_update: 未実装