# KnowledgeRetrieverAgent 詳細設計

## 1. 役割

KnowledgeRetrieverAgent は既知エラー、取得済み過去チケット情報、ナレッジベースから関連情報を探索する専門エージェントである。
LogAnalyzerAgent が返した兆候や IntakeAgent の分類結果と照合し、根拠付きの候補を SuperVisorAgent へ返す。
文書系ナレッジは [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.KnowledgeRetrieverAgent.document_sources に定義した名称、説明、格納先パスに従って管理し、DeepAgents backend のファイルシステム面から参照する方針とする。
明示 ticket ID があり対応 MCP ツールが有効な場合の一次取得は IntakeAgent が担当し、KnowledgeRetrieverAgent は workspace へ投影された ticket 情報と添付ファイルを優先的に参照する方針とする。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent に返す
- 参照先: shared/context.md、shared/progress.md、config 定義済み文書群、workspace に取り込まれた ticket 情報 / 添付ファイル、agent working memory

## 3. 入力

- CaseState の raw_issue、intake_category、intake_investigation_focus
- CaseState の external_ticket_id、internal_ticket_id、intake_ticket_context_summary、intake_ticket_artifacts
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
   Intake / LogAnalyzer の結果から比較軸を決め、DeepAgents に渡す検索依頼を組み立てる。
2. KB・履歴探索
   config で定義した document_sources を DeepAgents backend から参照し、検索判断そのものは DeepAgents に委ねる。IntakeAgent が workspace へ保存した ticket 情報や添付ファイルも根拠候補として参照する。必要な詳細が不足する場合のみ、external_ticket と internal_ticket による追加取得または再取得を行う。
3. 根拠評価
   類似度、再現条件、影響範囲の一致度に加え、問い合わせ文に source 名の明示一致がある場合はその source を優先して候補を絞る。
4. 抜粋化
   SuperVisorAgent と DraftWriterAgent が採用判断しやすいよう、DeepAgents が選んだ重要抜粋または主要文書の raw snippet を返す。

返却結果は source 単位で構造化し、少なくとも source_name、summary、matched_paths、evidence を含める。ここでの `summary` は意味要約ではなく raw snippet である。
Supervisor はこの結果から、どの document_source を根拠として採用したかを判断する。
最終採用した source 名は CaseState の knowledge_retrieval_final_adopted_source にも保持する。

## 7. 共有メモリ更新

- shared/context.md には採用候補と根拠のみを残す
- working.md には検索履歴、未採用候補、探索メモに加え、source ごとの raw result を残す
- working.md への既定書き込みは write_working_memory builtin が担当する

## 8. plan / action 差分

- plan モード: 検索先、検索語、照合観点を返す
- action モード: 実際に KB・過去事例探索を行い、根拠付き候補を返す

## 9. 実装方針

- document_sources は config.yml で名称、説明、格納先パスを管理し、DeepAgents backend ではそれらの path をルート配下へ mount または route して read / grep / glob 対象に含める
- document_sources の backend 上の仮想パスは /knowledge/<source_name>/ を標準とし、たとえば python312_manual は /knowledge/python312_manual/、denodo93_manual は /knowledge/denodo93_manual/ として見せる
- `search_documents` の builtin 実装は DeepAgents に検索判断を委ね、結果 payload の組み立てと constraint_mode に応じた後段整形は KnowledgeRetriever 側 caller で行う
- external_ticket と internal_ticket は論理ツールを分け、各々 config で指定した MCP ツールへ接続する方針とする
- search_documents、external_ticket、internal_ticket の有効化と供給元は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.logical_tools 配下で管理する
- logical_tools は enabled: false による無効化、provider: builtin による builtin 実装利用、provider: mcp による外部 MCP 利用の 3 パターンで扱う
- external_ticket_id と internal_ticket_id は CaseState に保持し、IntakeAgent が初期 hydration に使い、KnowledgeRetrieverAgent は必要時の再取得に使う
- external_ticket と internal_ticket は tools.logical_tools.external_ticket / internal_ticket で有効化と provider を定義し、provider: mcp の場合は ToolRegistry がその binding を起動時に検証する
- 明示 ticket ID がない場合は RuntimeService が trace_id から `EXT-TRACE-...` と `INT-TRACE-...` を自動生成する
- default 実装では external_ticket / internal_ticket が利用できない場合、情報を取得できない旨を返す
- LogAnalyzerAgent の出力と競合しないよう、KnowledgeRetrieverAgent は「既知情報との照合」に責務を寄せ、一次的な ticket hydration の責務は IntakeAgent に寄せる

## 10. 未決事項

- document_sources の選択順序と検索優先順位
- 根拠スコアを構造化データとして保持するかどうか
- IntakeAgent が投影した ticket 添付ファイルを document_sources 的にどう検索対象化するか