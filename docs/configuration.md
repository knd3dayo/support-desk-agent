# 設定ガイド

## 1. 目的

本書は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の主要設定方針、とくに KnowledgeRetrieverAgent の文書ソースと ticket source 設定を説明する。

## 2. Knowledge Retrieval 設定

`knowledge_retrieval.document_sources` では、KnowledgeRetrieverAgent が参照する文書ソースを定義する。

- name: source を識別する論理名。backend 上では `/knowledge/<name>/` に対応する
- description: source の内容説明
- path: 実ファイルの格納先パス

例:

```yaml
support_ope_agents:
  knowledge_retrieval:
    document_sources:
      - name: python312_manual
        description: Python 3.12 の公式仕様・標準ライブラリ資料
        path: ./docsources/python312_manual
      - name: growi_knowledge
        description: 社内 GROWI にエクスポートした運用ナレッジ
        path: ./docsources/growi_knowledge
      - name: ai-platform-poc
        description: 生成AI基盤のアーキテクチャ検討資料
        path: /home/user/source/repos/ai-platform-poc
```

## 3. DeepAgents backend との対応

- KnowledgeRetrieverAgent は `CompositeBackend` を使い、複数の document_sources を 1 つの backend に束ねる
- 各 source は `/knowledge/<source_name>/` に route する
- default backend は `StateBackend` とし、knowledge 以外の一時ファイルは state 側で扱う

例:

- `/knowledge/python312_manual/` → `python312_manual.path`
- `/knowledge/growi_knowledge/` → `growi_knowledge.path`

## 4. Ticket Source 設定

`knowledge_retrieval.external_ticket` と `knowledge_retrieval.internal_ticket` では、各論理ツールに対応する MCP tool を指定する。

- mcp_server: MCP manifest 上の server 名
- mcp_tool: 呼び出す tool 名
- description: source の説明

## 5. 優先順位

KnowledgeRetrieverAgent の ticket source 解決は次の優先順位に従う。

1. `tools.overrides`
2. `knowledge_retrieval.external_ticket` / `knowledge_retrieval.internal_ticket`
3. 既定 unavailable 実装

## 6. document_sources 未設定時

`knowledge_retrieval.document_sources` が空の場合、既定の `search_documents` 実装は「参照可能なドキュメントがないので回答できません。」という旨のメッセージを返す。
この状態では KnowledgeRetrieverAgent は document source を根拠にした回答を返さず、ticket source が設定されていればそちらの結果のみを補助情報として扱う。

## 7. source 単位の結果

KnowledgeRetrieverAgent は source ごとに次のような結果を返す方針とする。

- source_name
- source_description
- summary
- matched_paths
- evidence

Supervisor はこの結果から採用 source を選び、shared/context.md に採用した source 名を残す。