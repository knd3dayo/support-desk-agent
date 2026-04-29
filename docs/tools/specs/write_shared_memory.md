# write_shared_memory

## 1. 目的

shared/context.md、shared/progress.md、shared/summary.md へ調査結果や進捗を反映する。

## 2. 利用エージェント

- SuperVisorAgent
- IntakeAgent
- BackSupportEscalationAgent
- BackSupportInquiryWriterAgent

## 3. 既定実装 / 接続点

- 論理ツール名: write_shared_memory
- 既定実装: [src/support_desk_agent/tools/default_write_shared_memory.py](/home/user/source/repos/support-desk-agent/src/support_desk_agent/tools/default_write_shared_memory.py)
- payload 型: [src/support_desk_agent/util/shared_memory_payload.py](/home/user/source/repos/support-desk-agent/src/support_desk_agent/util/shared_memory_payload.py)

## 4. 実装状況

- 区分: implemented
- 実装済み