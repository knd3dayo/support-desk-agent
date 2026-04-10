# IntakeAgent 用ツール設計

## 1. 対象ツール

- pii_mask
- classify_ticket

## 2. 共通ツール参照

- shared memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- pii_mask: API キー、アクセストークン、Bearer token、secret、password などの秘匿値をマスキングする。実運用ではローカル LLM へ差し替える前提とし、PoC 段階では [src/support_ope_agents/config/models.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/config/models.py) で定義される LLM 設定を使用する既定実装を ToolRegistry に登録する。
- classify_ticket: 問い合わせカテゴリ、緊急度、初期調査観点を分類する。カテゴリ値は workflow_kind と同じ語彙体系である specification_inquiry / incident_investigation / ambiguous_case を使う。PoC 段階では [src/support_ope_agents/config/models.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/config/models.py) で定義される LLM 設定を使用する既定実装を ToolRegistry に登録する。

## 4. 実装状況

- pii_mask: 実装済み
- classify_ticket: 実装済み
- write_shared_memory: 共通ツールとして実装済み

## 5. 補足

- これらは ToolRegistry 上の論理ツール名であり、実装は builtin / MCP override により差し替え可能とする。