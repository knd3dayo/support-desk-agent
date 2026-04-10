# KnowledgeRetrieverAgent 用ツール設計

## 1. 対象ツール

- search_documents
- external_ticket
- internal_ticket

## 2. 共通ツール参照

- working memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- search_documents: [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の knowledge_retrieval.document_sources に定義した文書群を DeepAgents backend 経由で検索する。各 source は name、description、path を持ち、backend では path を mount または route して read / grep / glob の探索面に載せる想定とする。
- external_ticket: 顧客向けケースを取得する論理ツール。実運用では tools.overrides が優先され、未指定なら knowledge_retrieval.external_ticket で指定した MCP ツールを ToolRegistry が自動利用する。入力 ticket_id は CLI / API から明示指定でき、未指定時は trace_id 由来の `EXT-TRACE-...` を使う。
- internal_ticket: 内部管理用チケットを取得する論理ツール。実運用では tools.overrides が優先され、未指定なら knowledge_retrieval.internal_ticket で指定した MCP ツールを ToolRegistry が自動利用する。入力 ticket_id は CLI / API から明示指定でき、未指定時は trace_id 由来の `INT-TRACE-...` を使う。

## 4. 実装状況

- search_documents: 既定実装あり。document_sources 配下の Markdown を走査し、summary、matched_paths、evidence を返す
- external_ticket: 既定では利用不可メッセージを返す
- internal_ticket: 既定では利用不可メッセージを返す
- write_working_memory: 共通ツールとして実装済み。KnowledgeRetrieverAgent の working.md に検索要約を残す

## 5. 補足

- DeepAgents backend では CompositeBackend や FilesystemBackend の route を使い、config 定義された document_sources を /knowledge/<source_name>/ 配下へ検索可能なファイル面として公開する方針を採る
- 例: python312_manual の path が /srv/docs/python312_manual の場合、backend では /knowledge/python312_manual/ へ route し、その配下を read / glob / grep できるようにする
- 優先順位は tools.overrides > knowledge_retrieval.external_ticket / internal_ticket > 既定 unavailable 実装 とする
- external_ticket と internal_ticket の既定実装は空であり、MCP ツールが未設定なら「情報を取得できない」旨を返す
- Supervisor は knowledge_retrieval_results の中から final adopted source を 1 件選び、state の knowledge_retrieval_final_adopted_source と shared/context.md に反映する

## 6. ticket source の I/O 契約

- external_ticket / internal_ticket の呼び出し入力は `ticket_id` を標準とする
- `ticket_id` は RuntimeService が state の external_ticket_id / internal_ticket_id から渡す
- 明示指定がなければ RuntimeService が trace_id から既定値を生成する
- MCP 実装は、少なくとも ticket_id に対応する要約テキスト、もしくは JSON 文字列を返す
- handler が旧シグネチャで `ticket_id` を受け取れない場合でも既定実装は後方互換で呼べるが、新規 MCP 実装では `ticket_id` 対応を前提とする