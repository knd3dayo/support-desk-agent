# check_policy

## 1. 目的

ドラフトが内部ポリシーや回答基準に抵触しないか確認する。

## 2. 利用エージェント

- ComplianceReviewerAgent

## 3. 既定実装 / 接続点

- 論理ツール名: check_policy
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)

## 4. 実装状況

- 既定 builtin 実装あり

## 5. 既定 builtin の挙動

- agents.ComplianceReviewerAgent.document_sources を検索し、社内規定、政府ガイドライン、法令文書の概要候補を返す
- agents.ComplianceReviewerAgent.notice.required が true の場合、ドラフトに required_phrases のいずれかが含まれているか検査する
- 断定表現や過剰な約束を簡易検出し、revision_required の論点へ加える
- 結果は JSON で返し、status、issues、results、adopted_sources、notice_check を含む