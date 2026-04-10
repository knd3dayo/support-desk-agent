# search_documents

## 1. 目的

構成済み document_sources を横断検索し、関連ナレッジや根拠候補を収集する。

## 2. 利用エージェント

- KnowledgeRetrieverAgent

## 3. 既定実装 / 接続点

- 論理ツール名: search_documents
- 既定実装: [src/support_ope_agents/tools/default_search_documents.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_search_documents.py)
- 参照定義は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.KnowledgeRetrieverAgent.document_sources に置く

## 4. 実装状況

- 実装済み