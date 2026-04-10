# KnowledgeRetrieverAgent 詳細設計

## 1. 役割

KnowledgeRetrieverAgent は既知エラー、過去チケット、ナレッジベースから関連情報を探索する専門エージェントである。
LogAnalyzerAgent が返した兆候や IntakeAgent の分類結果と照合し、根拠付きの候補を SuperVisorAgent へ返す。
文書系ナレッジは [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の knowledge_retrieval.document_sources に定義した名称、説明、格納先パスに従って管理し、DeepAgents backend のファイルシステム面から参照する方針とする。
また、過去チケットは external_ticket と internal_ticket に分け、各々 [config.yml](/home/user/source/repos/support-ope-agents/config.yml) で指定した MCP ツールを用いて取得する方針とする。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent に返す
- 参照先: shared/context.md、shared/progress.md、config 定義済み文書群、external_ticket、internal_ticket、agent working memory

## 3. 入力

- CaseState の raw_issue、intake_category、intake_investigation_focus
- CaseState の external_ticket_id、internal_ticket_id
- shared/context.md の確定事実
- LogAnalyzerAgent の返した異常兆候や例外名

## 4. 出力

CaseState へ直に固定反映する項目はまだ少ないが、Supervisor が investigation_summary へ統合する素材を返す。

共有メモリへ反映する主な出力:

- shared/context.md: 採用した KB 候補、過去事例、根拠リンク
- shared/progress.md: 検索観点、未解決の確認事項

## 5. 使用ツール

KnowledgeRetrieverAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/search_documents.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/search_documents.md)
- [docs/tools/specs/external_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/external_ticket.md)
- [docs/tools/specs/internal_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/internal_ticket.md)
- [docs/tools/specs/write_working_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_working_memory.md)

## 6. 処理内容

1. 検索観点整理
   Intake / LogAnalyzer の結果から検索語と比較軸を決める。
2. KB・履歴探索
   config で定義した document_sources を DeepAgents backend から参照し、external_ticket と internal_ticket も分けて照会して候補を集める。ticket source へ渡す ID は、CLI / API から明示指定された external_ticket_id / internal_ticket_id を優先し、未指定時は trace_id 由来の既定値を使う。
3. 根拠評価
   類似度、再現条件、影響範囲の一致度で候補を絞る。
4. 要約化
   SuperVisorAgent が採用判断しやすい形で要約して返す。

返却結果は source 単位で構造化し、少なくとも source_name、summary、matched_paths、evidence を含める。
Supervisor はこの結果から、どの document_source を根拠として採用したかを判断する。
最終採用した source 名は CaseState の knowledge_retrieval_final_adopted_source にも保持する。

## 7. 共有メモリ更新

- shared/context.md には採用候補と根拠のみを残す
- working.md には検索履歴、未採用候補、探索メモを残す
- working.md への既定書き込みは write_working_memory builtin が担当する

## 8. plan / action 差分

- plan モード: 検索先、検索語、照合観点を返す
- action モード: 実際に KB・過去事例探索を行い、根拠付き候補を返す

## 9. 実装方針

- document_sources は config.yml で名称、説明、格納先パスを管理し、DeepAgents backend ではそれらの path をルート配下へ mount または route して read / grep / glob 対象に含める
- document_sources の backend 上の仮想パスは /knowledge/<source_name>/ を標準とし、たとえば python312_manual は /knowledge/python312_manual/、denodo93_manual は /knowledge/denodo93_manual/ として見せる
- external_ticket と internal_ticket は論理ツールを分け、各々 config で指定した MCP ツールへ接続する方針とする
- external_ticket_id と internal_ticket_id は CaseState に保持し、KnowledgeRetrieverAgent はそれを ticket source 呼び出しの引数として渡す
- external_ticket と internal_ticket は tools.overrides に明示指定がなければ、knowledge_retrieval.external_ticket / internal_ticket で指定した mcp_server / mcp_tool から ToolRegistry が自動で MCP binding を組み立てる
- 明示 ticket ID がない場合は RuntimeService が trace_id から `EXT-TRACE-...` と `INT-TRACE-...` を自動生成する
- default 実装では external_ticket / internal_ticket が利用できない場合、情報を取得できない旨を返す
- LogAnalyzerAgent の出力と競合しないよう、KnowledgeRetrieverAgent は「既知情報との照合」に責務を寄せる

## 10. 未決事項

- document_sources の選択順序と検索優先順位
- 根拠スコアを構造化データとして保持するかどうか
- DeepAgents backend で external_ticket / internal_ticket 結果を一時ファイルへ投影するかどうか