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
- [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.ComplianceReviewerAgent.document_sources で定義した社内規定、政府ガイドライン、法令などの根拠文書
- [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.ComplianceReviewerAgent.notice.required / required_phrases で定義した注意文ルール
- [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.ComplianceReviewerAgent.max_review_loops で定義した DraftWriterAgent への再生成上限回数

## 4. 出力

CaseState へ直接固定反映する項目はまだ限定的だが、Supervisor が draft_response 再生成や承認遷移判断に使うレビュー結果を返す。

共有メモリへ反映する主な出力:

- shared/progress.md: 差戻し要否、修正観点、承認前に残る懸念点
- compliance_review_summary: ポリシー照合と表現チェックの要約
- compliance_review_issues: 修正が必要な論点一覧
- compliance_notice_present: 注意文が含まれていたかどうか
- compliance_revision_request: DraftWriterAgent へ返す修正観点

## 5. 使用ツール

ComplianceReviewerAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/check_policy.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/check_policy.md)
- [docs/tools/specs/request_revision.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/request_revision.md)

## 6. 処理内容

1. 事実整合チェック
   調査結果と矛盾した記述がないかを見る。
2. 根拠文書検索
   DeepAgents backend の /policy/<source_name>/ 配下に mount した document_sources を参照し、社内規定、政府ガイドライン、法令の根拠候補を抽出する。
3. 表現・ポリシーチェック
   過剰な断定、不要な約束、禁則表現がないかを見る。
4. 注意文チェック
   notice.required が true の場合、ドラフトに「生成AIは誤った回答をすることがあります」相当の注意文が含まれているか確認する。
5. 差戻し要否判定
   差戻しが必要なら修正観点を整理して返す。
6. 再生成ループ判定
   SuperVisorAgent は compliance_revision_request を DraftWriterAgent へ返し、max_review_loops の範囲で再生成と再レビューを繰り返す。

## 7. 共有メモリ更新

- shared/progress.md には差戻し有無と修正論点のみを残す
- working.md を持つ場合は詳細なレビューコメントをそちらへ寄せる

## 8. plan / action 差分

- plan モード: どの観点でレビューするかを返す
- action モード: 実際のドラフトを検査し、承認可否または差戻し観点を返す

## 9. 実装方針

- Supervisor が review_focus を決め、その重点に沿って ComplianceReviewerAgent が差戻し観点を返す構成にする
- document_sources は agents.ComplianceReviewerAgent.document_sources で管理し、DeepAgents backend では /policy/<source_name>/ に route する
- ignore_patterns と ignore_patterns_file は既定の check_policy 実装が探索候補を絞るために使う
- max_review_loops は DraftWriterAgent との自動差戻しループ上限で、既定値は 3 とする
- check_policy と request_revision の有効化と供給元は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.logical_tools 配下で管理する
- logical_tools は enabled: false による無効化、provider: builtin による builtin 実装利用、provider: mcp による外部 MCP 利用の 3 パターンで扱う
- provider: mcp の場合は manifest と server / tool 定義を起動時に検証し、builtin 実装では document_sources 検索、注意文チェック、必要時の LLM 補助レビューを行う
- 将来的には差戻し理由を構造化して、再生成ループの自動制御に利用できるようにする

## 10. 未決事項

- 差戻し結果のデータ構造
- 自動承認可能な条件の定義
- ポリシールールの外部設定化