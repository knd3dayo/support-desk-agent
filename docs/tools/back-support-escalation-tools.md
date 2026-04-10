# BackSupportEscalationAgent 用ツール設計

## 1. 対象ツール

- scan_workspace_artifacts

## 2. 共通ツール参照

- shared memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- scan_workspace_artifacts: 追加で渡せるログ、設定ファイル、証跡の有無を確認する

## 4. 実装状況

- read_shared_memory: 共通ツールとして実装済み
- scan_workspace_artifacts: 未実装
- write_shared_memory: 共通ツールとして実装済み