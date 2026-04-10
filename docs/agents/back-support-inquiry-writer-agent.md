# BackSupportInquiryWriterAgent 詳細設計

## 1. 役割

BackSupportInquiryWriterAgent は、BackSupportEscalationAgent が整理した材料をもとに、バックサポート問い合わせ文案または追加ログ提供依頼文案を作成する専門エージェントである。
ユーザーへ返す文案として、必要なログ取得依頼、再現手順の確認依頼、現在までの調査状況を分かりやすくまとめる。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: BackSupportEscalationAgent
- 呼び出し先: SuperVisorAgent、ApprovalAgent
- 接続先: 承認後は TicketUpdateAgent または外部問い合わせ送信フローへ接続する

## 3. 入力

- escalation_summary
- escalation_missing_artifacts
- shared/context.md の確定事実
- shared/progress.md の未解決事項
- intake_urgency

## 4. 出力

CaseState へ反映しうる主な出力:

- escalation_draft
- draft_response

共有メモリへ反映する主な出力:

- shared/context.md: バックサポート問い合わせの目的、添付予定資料、依頼事項
- shared/progress.md: 問い合わせ文案作成済み、承認待ち、送付待ち

## 5. 使用ツール

BackSupportInquiryWriterAgent の使用ツール詳細は次を参照する。

- 共通事項: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- BackSupportInquiryWriterAgent 用ツール: [docs/tools/back-support-inquiry-writer-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/back-support-inquiry-writer-tools.md)

## 6. 処理内容

1. 材料確認
   BackSupportEscalationAgent が整理した事実、未解決事項、必要ログ一覧を確認する。
2. 文案構成
   背景、現象、実施済み調査、欲しい追加資料、回答期限感を整理する。
3. 文案生成
   ユーザーへ返す問い合わせ文案として、必要ログや再現手順の依頼を分かりやすく生成する。
4. 承認回付
   SuperVisorAgent に返し、ApprovalAgent で確認できる状態にする。

## 7. 共有メモリ更新

- shared/context.md には問い合わせ文案の要点のみを残す
- shared/progress.md にはエスカレーション文案作成済みであることを残す

## 8. plan / action 差分

- plan モード: どの情報を依頼する文案になるかを返す
- action モード: 実際の問い合わせ文案を生成する

## 9. 実装方針

- DraftWriterAgent とは分けて、通常回答ドラフトとエスカレーション問い合わせ文案の責務を分離する
- 顧客向けに返す文案と、バックサポートへ渡す内部メモの境界を明確にする
- 実行クラスは [src/support_ope_agents/agents/back_support_inquiry_writer_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/back_support_inquiry_writer_agent.py) の BackSupportInquiryWriterPhaseExecutor とし、現時点では共有メモリ更新と問い合わせ文案組み立てを担当する

## 10. 未決事項

- 問い合わせ送付先が顧客か内部バックサポートかで文面テンプレートを分けるかどうか
- escalation_draft と draft_response を別々に持つか、共通化するか