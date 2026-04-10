# external_ticket

## 1. 目的

顧客向け外部チケット情報を取得し、既知事例や現状把握に使う。

## 2. 利用エージェント

- KnowledgeRetrieverAgent

## 3. 既定実装 / 接続点

- 論理ツール名: external_ticket
- 既定では未接続で、MCP override または [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の knowledge_retrieval.external_ticket で構成する
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)

## 4. 実装状況

- 既定実装なし