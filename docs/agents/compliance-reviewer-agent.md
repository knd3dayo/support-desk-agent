# ComplianceReviewerAgent 詳細設計

## 1. 役割

ComplianceReviewerAgent は回答ドラフトが事実、ポリシー、表現上の制約に反していないかを検査する専門エージェントである。
差戻しの必要があれば、その理由と修正観点を SuperVisorAgent 経由で DraftWriterAgent へ返す。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の draft_review フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent が評価する
- 参照先: draft_response、shared/context.md、shared/progress.md

## 3. 入力

- draft_response
- shared/context.md の確定事実
- review_focus
- intake_category、intake_urgency

## 4. 出力

CaseState へ直接固定反映する項目はまだ限定的だが、Supervisor が draft_response 再生成や承認遷移判断に使うレビュー結果を返す。

共有メモリへ反映する主な出力:

- shared/progress.md: 差戻し要否、修正観点、承認前に残る懸念点

## 5. 使用ツール

- check_policy
- request_revision

## 6. 処理内容

1. 事実整合チェック
   調査結果と矛盾した記述がないかを見る。
2. 表現・ポリシーチェック
   過剰な断定、不要な約束、禁則表現がないかを見る。
3. 差戻し要否判定
   差戻しが必要なら修正観点を整理して返す。

## 7. 共有メモリ更新

- shared/progress.md には差戻し有無と修正論点のみを残す
- working.md を持つ場合は詳細なレビューコメントをそちらへ寄せる

## 8. plan / action 差分

- plan モード: どの観点でレビューするかを返す
- action モード: 実際のドラフトを検査し、承認可否または差戻し観点を返す

## 9. 実装方針

- Supervisor が review_focus を決め、その重点に沿って ComplianceReviewerAgent が差戻し観点を返す構成にする
- 将来的には差戻し理由を構造化して、再生成ループの自動制御に利用できるようにする

## 10. 未決事項

- 差戻し結果のデータ構造
- 自動承認可能な条件の定義
- ポリシールールの外部設定化