# 設定ガイド

## 1. 目的

本書は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の主要設定方針、とくに KnowledgeRetrieverAgent の文書ソースと ticket source 設定を説明する。

## 2. Knowledge Retrieval 設定

`knowledge_retrieval.document_sources` では、KnowledgeRetrieverAgent が参照する文書ソースを定義する。

- name: source を識別する論理名。backend 上では `/knowledge/<name>/` に対応する
- description: source の内容説明
- path: 実ファイルの格納先パス

`knowledge_retrieval.ignore_patterns` と `knowledge_retrieval.ignore_patterns_file` では、文書探索から除外するパスを指定する。

- ignore_patterns: source root からの相対パスに対する glob パターン。未指定時は `.git`、`node_modules`、`.venv`、`__pycache__` などを既定で除外する
- ignore_patterns_file: 1 行 1 パターンの追加除外ファイル。空行と `#` コメントは無視する

例:

```yaml
support_ope_agents:
  knowledge_retrieval:
    ignore_patterns:
      - .*
      - '**/.*'
      - node_modules/**
      - '**/node_modules/**'
    ignore_patterns_file: ./.support-ope-ignore
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

現時点の support-ope-agents では、ignore_patterns は主に既定の `search_documents` 実装で使う。DeepAgents の FilesystemBackend 自体には `.gitignore` を自動解釈する共通設定はないため、support-ope-agents 側で探索候補を絞る。

例:

- `/knowledge/python312_manual/` → `python312_manual.path`
- `/knowledge/growi_knowledge/` → `growi_knowledge.path`

## 4. Intake 設定

`intake.pii_mask.enabled` では、IntakeAgent が PII マスキングを既定で実行するかを制御する。

- enabled: true のときのみ pii_mask を実行する
- 既定値: false
- Supervisor はこの設定を参照せず、PII マスクの実行有無は IntakeAgent 側でのみ判断する

例:

```yaml
support_ope_agents:
  intake:
    pii_mask:
      enabled: false
```

IntakeAgent は明示指定された external_ticket_id / internal_ticket_id があり、対応する MCP ツールが有効な場合に、ticket 情報と添付ファイルを case workspace 配下へ取り込む。
保存先の既定値は `.artifacts/intake/` とし、後続 agent はその投影結果を再利用する。

## 5. Intake Ticket Source 設定

`intake.external_ticket` と `intake.internal_ticket` では、IntakeAgent と KnowledgeRetrieverAgent が共有する各論理ツールに対応する MCP tool を指定する。

- mcp_server: MCP manifest 上の server 名
- mcp_tool: 呼び出す tool 名
- description: source の説明

例:

```yaml
support_ope_agents:
  intake:
    pii_mask:
      enabled: false
    external_ticket:
      description: 顧客向けケース管理システム
      mcp_server: support-ticket-mcp
      mcp_tool: get_external_ticket
    internal_ticket:
      description: 内部管理用チケットシステム
      mcp_server: support-ticket-mcp
      mcp_tool: get_internal_ticket
```

external_ticket_id と internal_ticket_id は config.yml ではなく実行入力で与える。

- CLI: `plan` / `action` / `resume-customer-input` で `--external-ticket-id` と `--internal-ticket-id` を受け付ける
- API: 同名フィールドを request body で受け付ける
- 未指定時は trace_id から自動生成し、外部は `EXT-TRACE-...`、内部は `INT-TRACE-...` を使う

trace_id と ticket ID の関係を固定しておくことで、ケース実行単位の追跡と ticket source 照会の相関を取りやすくする。

### 5.1 MCP ツール I/O 契約

external_ticket / internal_ticket に対応する MCP ツールは、少なくとも次の I/O 契約を満たす前提とする。

- 入力: `ticket_id` を受け取る
- 出力: 指定 ID に対応するチケットの要約または詳細を文字列または JSON で返す
- 未取得時: 「not configured」ではなく、取得不可または未発見である旨が分かる応答を返す

推奨 JSON 例:

```json
{
  "ticket_id": "EXT-123",
  "summary": "チケット要約",
  "title": "件名",
  "description": "詳細本文",
  "attachments": [
    {
      "filename": "application.log",
      "content_base64": "..."
    },
    {
      "filename": "memo.txt",
      "content": "添付本文"
    },
    {
      "filename": "already-downloaded.pdf",
      "path": "/mounted/path/already-downloaded.pdf"
    }
  ]
}
```

- attachments は省略可能
- IntakeAgent は attachments を .artifacts/intake/ へ保存する
- LogAnalyzerAgent は .artifacts/intake/ のログ系添付を通常の workspace ログより優先して解析候補にする
- KnowledgeRetrieverAgent は hydration 済み ticket 要約と添付パスを優先して使い、不足時のみ再取得する

既定実装は後方互換のため `ticket_id` を受け取らない handler でも動くが、MCP 側の正式契約としては `ticket_id` 入力を推奨する。

IntakeAgent と KnowledgeRetrieverAgent は同じ external_ticket / internal_ticket binding を共有してよいが、責務は分ける。

- IntakeAgent: 明示 ticket ID がある場合の初期 hydration と workspace への投影
- KnowledgeRetrieverAgent: 取得済み情報を使った照合と、必要時のみの再取得

## 6. 優先順位

KnowledgeRetrieverAgent の ticket source 解決は次の優先順位に従う。

1. `tools.overrides`
2. `intake.external_ticket` / `intake.internal_ticket`
3. 後方互換のための `knowledge_retrieval.external_ticket` / `knowledge_retrieval.internal_ticket`
4. 既定 unavailable 実装

## 6. LibreOffice 設定

Office 系ファイルの PDF 変換では `tools.libreoffice_command` を使う。

- 指定値は `soffice` のような実行名でも、絶対パスでもよい
- 未指定時は `soffice`、`libreoffice` の順で探索する

例:

```yaml
support_ope_agents:
  tools:
    libreoffice_command: /usr/bin/soffice
```

## 7. document_sources 未設定時

`knowledge_retrieval.document_sources` が空の場合、既定の `search_documents` 実装は「参照可能なドキュメントがないので回答できません。」という旨のメッセージを返す。
この状態では KnowledgeRetrieverAgent は document source を根拠にした回答を返さず、ticket source が設定されていればそちらの結果のみを補助情報として扱う。

## 8. source 単位の結果

KnowledgeRetrieverAgent は source ごとに次のような結果を返す方針とする。

- source_name
- source_description
- summary
- matched_paths
- evidence

Supervisor はこの結果から採用 source を選び、shared/context.md に採用した source 名を残す。
また、最終採用した 1 件は CaseState の `knowledge_retrieval_final_adopted_source` に保持する。

## 9. instruction override と tool docs 下書き

- Supervisor の Intake 出力評価観点は [src/support_ope_agents/instructions/defaults/SuperVisorAgent.md](/home/user/source/repos/support-ope-agents/src/support_ope_agents/instructions/defaults/SuperVisorAgent.md) に既定値を置く
- `config_paths.instructions_path` を設定すると、同名の SuperVisorAgent.md でこの評価観点を丸ごと上書きできる
- docs/tools の下書きは `support-ope-agents export-tool-docs --config config.yml --output-dir docs/tools/generated` で生成できる