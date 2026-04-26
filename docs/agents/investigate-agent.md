# InvestigateAgent 詳細設計

## 1. 役割

InvestigateAgent は仕様確認、ログ解析、ナレッジ探索、回答ドラフト作成を一体で担う統合エージェントである。
SuperVisorAgent から調査依頼を受け、問い合わせ種別に応じて必要な証跡確認と文書探索を行い、その結果を investigation_summary と draft_response にまとめる。

## 2. 主な責務

- specification_inquiry では document source と ticket 情報を優先して確認する
- incident_investigation ではログ解析結果と既知ナレッジを突き合わせる
- ambiguous_case では不足情報や未確定事項を明示しつつ、追加調査が必要か判断材料を返す
- Sample 実装では ZIP 添付の中身確認と展開、PDF・画像・Office 添付の分析、ログ時間帯抽出を built-in tool でそのまま実行できる
- 各実行で shared/context.md、shared/progress.md、shared/summary.md を更新する

## 3. 入出力

CaseState へ反映する主な項目は次のとおり。

- investigation_summary
- log_analysis_summary
- log_analysis_file
- knowledge_retrieval_summary
- knowledge_retrieval_results
- knowledge_retrieval_adopted_sources
- knowledge_retrieval_final_adopted_source
- draft_response

## 4. 参照設定

- 文書ソースは [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.InvestigateAgent.document_sources で定義する
- 検索結果の保持粒度は agents.InvestigateAgent.result_mode で調整する
- constraint_mode は instruction と runtime 制約の適用方針を決める

## 5. 実装メモ

- 実行本体は [src/support_ope_agents/agents/investigate_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/investigate_agent.py) にある
- 内部では log_analyzer_executor、knowledge_retriever_executor、draft_writer_executor を組み合わせる
- user-facing な出力では旧 split role 名を出さず、調査結果と根拠資料として表現する