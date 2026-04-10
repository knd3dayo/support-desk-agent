# pii_mask

## 1. 目的

API キー、アクセストークン、password などの秘匿値をマスキングし、共有出力へ安全に流せる形へ整える。

## 2. 利用エージェント

- IntakeAgent

## 3. 既定実装 / 接続点

- 論理ツール名: pii_mask
- 既定実装: [src/support_ope_agents/tools/default_pii_mask.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_pii_mask.py)
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- IntakeAgent では [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.IntakeAgent.pii_mask.enabled が true の場合のみ使う。既定値は false。

## 4. 実装状況

- 実装済み