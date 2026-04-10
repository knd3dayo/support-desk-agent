# KnowledgeRetrieverAgent 用ツール設計

## 1. 対象ツール

- search_kb
- search_ticket_history

## 2. 共通ツール参照

- working memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- search_kb: ナレッジベースや仕様文書から関連候補を検索する
- search_ticket_history: 過去チケットや既知障害履歴から類似事例を探索する

## 4. 実装状況

- search_kb: 未実装
- search_ticket_history: 未実装
- write_working_memory: 共通ツールとして未実装