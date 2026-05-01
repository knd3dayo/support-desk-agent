# Configuration Guide

## 1. 目的

本書は [config.yml](/home/user/source/repos/support-desk-agent/config.yml) の主要設定方針を説明する。
現行設計では、仕様確認、ログ解析、ナレッジ探索、回答ドラフト作成は InvestigateAgent に集約される。

## 2. 主要 Agent 設定

### InvestigateAgent

`agents.InvestigateAgent.document_sources` で文書探索対象を定義する。

- name: source を識別する論理名
- description: source の説明
- path: 実ファイルの格納先

`agents.InvestigateAgent.result_mode` は探索結果の保持粒度を表す。

- relaxed: 既定値。要点中心の整形済み結果を返す
- raw_backend: 調査用。raw payload も保持する

例:

```yaml
support_desk_agent:
  agents:
    InvestigateAgent:
      result_mode: relaxed
      document_sources:
        - name: product_manual
          description: 製品仕様書
          path: ./docsources/product_manual
```

### SuperVisorAgent

`agents.SuperVisorAgent.max_investigation_loops` で再調査回数の上限を制御する。

- 0: 再調査しない
- 1: 新事実が出た場合に 1 回だけ再調査する
- 2 以上: 複数回の再調査を許可する

### IntakeAgent

IntakeAgent は `raw_issue` を直接分類入力として扱う。ticket 取得系の有効化は `tools.ticket_sources.external` / `tools.ticket_sources.internal` で制御する。

## 3. constraint_mode

全 Agent は `constraint_mode` を持てる。未指定時の既定値は `agents.default_constraint_mode` で設定できる。

- default: instruction と runtime 制約の両方を使う
- instruction_only: instruction のみを使う
- runtime_only: runtime 制約のみを使う
- bypass: instruction と runtime 制約を最小化する

`constraint_mode` は制約の適用方針であり、InvestigateAgent の `result_mode` とは別概念である。

## 4. ticket_sources

`tools.ticket_sources` では、`external_ticket` と `internal_ticket` が参照する外部チケット取得先を定義する。

- `external`: 顧客向け ticket の取得先
- `internal`: 内部管理 ticket の取得先
- `server`: MCP manifest 上の server 名
- `arguments`: ticket 取得 tool 群へ常に付与する固定引数

enabled な `ticket_sources` は CLI / API 起動時に `list_tools` で接続確認する。server 名の誤りや接続失敗がある場合は fail-fast で起動を中断する。

`external_ticket` / `internal_ticket` は `tools.logical_tools` ではなく、常に `tools.ticket_sources` から設定する。

## 5. logical tools

`tools.logical_tools` では、IntakeAgent、InvestigateAgent、SuperVisorAgent などが共有する論理ツールの有効化と供給元を定義する。

builtin と MCP の使い分け基準は [docs/tools/common.md](/home/user/source/repos/support-desk-agent/docs/tools/common.md) を参照する。
未実装または未接続の論理ツールをどちらで導入すべきか判断するときは [docs/tools/planned-logical-tools.md](/home/user/source/repos/support-desk-agent/docs/tools/planned-logical-tools.md) を起点にする。

ただし、すべての論理ツールを MCP へ差し替えられるわけではない。次のような workflow 内部状態に直結する tool は builtin 固定であり、`provider: mcp` を設定すると起動時に失敗する。

- `read_shared_memory`
- `write_shared_memory`
- `write_working_memory`
- `write_draft`
- `detect_log_format`

代表例:

- classify_ticket
- search_documents
- prepare_ticket_update

MCP を使う場合は `tools.mcp_manifest_path` を設定する。

## 6. ticket と workspace の扱い

- IntakeAgent は external / internal ticket の初期 hydration を担当する
- InvestigateAgent は workspace に投影された ticket 情報、添付、document source を優先して参照する
- 実チケット情報が不足する場合のみ、external_ticket / internal_ticket を再利用する
- IntakeAgent が保存した添付は `.artifacts/intake/` を起点に参照する

## 7. document source が空の場合

`agents.InvestigateAgent.document_sources` が空の場合、既定の `search_documents` は参照可能なドキュメントがない旨を返す。
この場合でも ticket 情報や workspace 内の証跡を使った補助調査は継続できるが、文書根拠は薄くなる。

## 8. 実装との対応

主要な反映先は次のとおり。

| 項目 | 実装箇所 | 役割 |
| --- | --- | --- |
| 制約の解決 | `src/support_desk_agent/runtime/runtime_harness_manager.py` | `constraint_mode` を解決する |
| instruction 読み込み | `src/support_desk_agent/instructions/loader.py` | role instruction を構成する |
| Investigate 実行 | `src/support_desk_agent/agents/investigate_agent.py` | 調査、検索、ドラフト作成を統合する |
| Supervisor 制御 | `src/support_desk_agent/agents/supervisor_agent.py` | 再調査、承認前の統制、エスカレーションを制御する |
| Tool binding | `src/support_desk_agent/tools/registry.py` | role ごとの論理ツールを解決する |

## 9. 推奨方針

- 非秘匿の運用設定は `config.yml` に集約する
- 秘匿情報は `.env` または実環境変数で管理する
- sample や PoC でも、document source 名は短く分かりやすく保つ
- user-facing な説明では旧 split role 名ではなく InvestigateAgent として説明する
