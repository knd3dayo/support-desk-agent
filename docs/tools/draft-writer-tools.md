# DraftWriterAgent 用ツール設計

## 1. 対象ツール

なし

## 2. 共通ツール参照

- draft 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- 現時点では role 固有ツールはなく、共通ツール write_draft を利用する。

## 4. 実装状況

- write_draft: 共通ツールとして実装済み。既定では `.artifacts/drafts/customer_response_draft.md` へ書き出す