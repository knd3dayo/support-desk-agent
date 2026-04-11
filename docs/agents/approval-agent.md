# ApprovalAgent 詳細設計

## 1. 役割

ApprovalAgent は WAITING_APPROVAL で人間の判断を受け付ける疑似エージェントである。
SuperVisorAgent がまとめた調査結果と回答ドラフトに対して、承認、差戻し、再調査のいずれかを受け取り、後続フェーズへ正しく接続する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の draft_review フェーズ
- 呼び出し先: TicketUpdateAgent、SuperVisorAgent investigation、SuperVisorAgent draft_review
- 接続先: approve なら TicketUpdateAgent、reject なら draft_review、reinvestigate なら investigation

## 3. 入力

- draft_response
- investigation_summary
- shared/context.md の確定事実
- shared/progress.md の進捗
- approval_decision
- trace_id

## 4. 出力

CaseState へ反映する主な出力:

- status = WAITING_APPROVAL
- current_agent = ApprovalAgent
- approval_decision
- next_action

共有メモリへ反映する主な出力:

- shared/progress.md: 承認待ち状態、差戻し理由、再調査指示

## 5. 使用ツール

ApprovalAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/record_approval_decision.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/record_approval_decision.md)

## 6. 処理内容

1. HITL 停止
   WAITING_APPROVAL でワークフローを停止し、人間判断を待つ。
2. 承認判断反映
   approve / reject / reinvestigate を workflow state に反映する。
3. 再開先選択
   承認判断に応じて TicketUpdateAgent、draft_review、investigation のいずれかへ遷移する。

## 7. 共有メモリ更新

- shared/progress.md に承認待ちか、差戻しか、再調査かを簡潔に残す
- 承認判断の詳細コメントを残す場合は .traces 側と progress に分離して持つ

## 8. plan / action 差分

- plan モード: 計画確認のための承認待ち案内を返す
- action モード: 実際の回答ドラフト確認と更新前判断を待つ

## 9. 実装方針

- ApprovalAgent は DeepAgent ではなく `create_node()` を持つ軽量 agent として実装し、親 workflow では `wait_for_approval` という node 名を維持して注入する
- 外部から見える継続識別子は trace_id に統一する
- 差戻しや再調査時の指示は state と shared/progress.md に残して再開可能にする
- record_approval_decision の有効化と供給元は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.logical_tools.record_approval_decision で管理する
- logical_tools は enabled: false による無効化、provider: builtin による builtin 実装利用、provider: mcp による外部 MCP 利用の 3 パターンで扱う
- provider: mcp の場合は manifest と server / tool 定義を起動時に検証し、current builtin は未実装プレースホルダーとして扱う

## 10. 未決事項

- 承認コメントの構造化データ化
- 複数承認者を想定するかどうか
- 承認履歴の UI/API 表現