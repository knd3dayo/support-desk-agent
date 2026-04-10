# DraftWriterAgent 詳細設計

## 1. 役割

DraftWriterAgent は調査結果を顧客向け回答ドラフトへ変換する専門エージェントである。
技術的事実と顧客向け表現の橋渡しを行い、必要な説明粒度とトーンに整形する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の draft_review フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent と ComplianceReviewerAgent に渡る
- 参照先: shared/context.md、shared/progress.md、調査結果、agent working memory

## 3. 入力

- investigation_summary
- shared/context.md の確定事実
- intake_category、intake_urgency
- 顧客への説明制約、必要なら追加レビュー観点

## 4. 出力

CaseState へ反映する主な出力:

- draft_response

共有メモリへ反映する主な出力:

- shared/context.md: ドラフトで採用した主張の要点
- shared/progress.md: ドラフト作成状況、差戻し待ちかどうか

## 5. 使用ツール

- write_draft

## 6. 処理内容

1. 材料整理
   調査結果から顧客に伝えるべき事実、未確定事項、次アクションを仕分ける。
2. ドラフト生成
   事実を過不足なく含みつつ、断定過剰や説明不足を避けた文面を作る。
3. 差戻し対応
   ComplianceReviewerAgent や Supervisor の指摘を受けて修正する。

## 7. 共有メモリ更新

- shared/context.md にはドラフトの根拠となる確定事実のみを残す
- working.md には文案の試行錯誤や差分メモを残す

## 8. plan / action 差分

- plan モード: どの観点で回答を構成するか、どの事実を前面に出すかを返す
- action モード: 実際の顧客向けドラフトを生成する

## 9. 実装方針

- DraftWriterAgent は最終回答生成に近い責務を持つため、Supervisor の review_focus を強く反映する
- コンプライアンス差戻し前提で、単発生成ではなく再生成しやすい入力構造を保つ

## 10. 未決事項

- ドラフトのテンプレート化をどこまで進めるか
- 敬語・トーン制御を設定化するかどうか