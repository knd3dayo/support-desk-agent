# KnowledgeRetrieverAgent 用ツール設計

## 1. 対象ツール

- search_documents
- external_ticket
- internal_ticket

## 2. 共通ツール参照

- working memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- search_documents: [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の knowledge_retrieval.document_sources に定義した文書群を DeepAgents backend 経由で検索する。各 source は name、description、path を持ち、backend では path を mount または route して read / grep / glob の探索面に載せる想定とする。
- external_ticket: 顧客向けケースを取得する論理ツール。実運用では tools.overrides が優先され、未指定なら knowledge_retrieval.external_ticket で指定した MCP ツールを ToolRegistry が自動利用する。
- internal_ticket: 内部管理用チケットを取得する論理ツール。実運用では tools.overrides が優先され、未指定なら knowledge_retrieval.internal_ticket で指定した MCP ツールを ToolRegistry が自動利用する。

## 4. 実装状況

- search_documents: 既定では backend 連携未実装
- external_ticket: 既定では利用不可メッセージを返す
- internal_ticket: 既定では利用不可メッセージを返す
- write_working_memory: 共通ツールとして未実装

## 5. 補足

- DeepAgents backend では CompositeBackend や FilesystemBackend の route を使い、config 定義された document_sources を /knowledge/<source_name>/ 配下へ検索可能なファイル面として公開する方針を採る
- 例: python312_manual の path が /srv/docs/python312_manual の場合、backend では /knowledge/python312_manual/ へ route し、その配下を read / glob / grep できるようにする
- 優先順位は tools.overrides > knowledge_retrieval.external_ticket / internal_ticket > 既定 unavailable 実装 とする
- external_ticket と internal_ticket の既定実装は空であり、MCP ツールが未設定なら「情報を取得できない」旨を返す