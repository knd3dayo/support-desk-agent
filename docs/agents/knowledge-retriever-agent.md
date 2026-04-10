# KnowledgeRetrieverAgent 詳細設計

## 1. 役割

KnowledgeRetrieverAgent は既知エラー、過去チケット、ナレッジベースから関連情報を探索する専門エージェントである。
LogAnalyzerAgent が返した兆候や IntakeAgent の分類結果と照合し、根拠付きの候補を SuperVisorAgent へ返す。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent に返す
- 参照先: shared/context.md、shared/progress.md、KB、過去チケット、agent working memory

## 3. 入力

- CaseState の raw_issue、intake_category、intake_investigation_focus
- shared/context.md の確定事実
- LogAnalyzerAgent の返した異常兆候や例外名

## 4. 出力

CaseState へ直に固定反映する項目はまだ少ないが、Supervisor が investigation_summary へ統合する素材を返す。

共有メモリへ反映する主な出力:

- shared/context.md: 採用した KB 候補、過去事例、根拠リンク
- shared/progress.md: 検索観点、未解決の確認事項

## 5. 使用ツール

KnowledgeRetrieverAgent の使用ツール詳細は次を参照する。

- 共通事項: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- KnowledgeRetrieverAgent 用ツール: [docs/tools/knowledge-retriever-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/knowledge-retriever-tools.md)

## 6. 処理内容

1. 検索観点整理
   Intake / LogAnalyzer の結果から検索語と比較軸を決める。
2. KB・履歴探索
   既知エラー、仕様文書、過去チケットを横断して候補を集める。
3. 根拠評価
   類似度、再現条件、影響範囲の一致度で候補を絞る。
4. 要約化
   SuperVisorAgent が採用判断しやすい形で要約して返す。

## 7. 共有メモリ更新

- shared/context.md には採用候補と根拠のみを残す
- working.md には検索履歴、未採用候補、探索メモを残す

## 8. plan / action 差分

- plan モード: 検索先、検索語、照合観点を返す
- action モード: 実際に KB・過去事例探索を行い、根拠付き候補を返す

## 9. 実装方針

- 当面は DeepAgent 想定の metadata を維持しつつ、検索系 tool の具体化を後続で進める
- LogAnalyzerAgent の出力と競合しないよう、KnowledgeRetrieverAgent は「既知情報との照合」に責務を寄せる

## 10. 未決事項

- KB と過去チケットの優先順位付け
- 根拠スコアを構造化データとして保持するかどうか
- 外部検索系 tool の MCP 化方針