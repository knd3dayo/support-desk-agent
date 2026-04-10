# LogAnalyzerAgent 詳細設計

## 1. 役割

LogAnalyzerAgent は調査フェーズでログ、エビデンス、ワークスペース情報から異常兆候と再現条件を抽出する専門エージェントである。
SuperVisorAgent の指示のもとでログ形式を見極め、例外、エラーレベル、時刻、再現条件に関わる手掛かりを整理する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent に返す
- 参照先: evidence、artifacts、shared/context.md、shared/progress.md、agent working memory

## 3. 入力

LogAnalyzerAgent が主要入力として扱うものは次のとおり。

- CaseState の raw_issue、intake_category、intake_urgency、intake_investigation_focus
- ケース workspace 配下の evidence / artifacts のログファイル
- shared/context.md の既知事実
- shared/progress.md の進捗と未解決事項

## 4. 出力

CaseState へ反映しうる主な出力:

- log_analysis_summary
- log_analysis_file

共有メモリへ反映する主な出力:

- shared/context.md: 採用したログ形式、主要な異常兆候、例外の有無
- shared/progress.md: どのログファイルを対象にしたか、追加調査が必要か

## 5. 使用ツール

LogAnalyzerAgent は論理ツールとして次を利用する。

- detect_log_format
- read_log_file
- run_python_analysis
- write_working_memory

## 6. 処理内容

LogAnalyzerAgent の処理は次の段階を基本とする。

1. 対象ログ選定
   evidence / artifacts から候補ログを収集し、最も有力なファイルを選ぶ。
2. ログ形式推定
   ファイル先頭 100 行前後から syslog / log4j / ISO 8601 / Java stack trace などの形式を推定する。
3. パターン生成と検索
   時刻、severity、例外名、スタックフレーム用の正規表現を生成し、ログ全体を検索する。
4. 要約化
   形式、主要一致件数、例外有無を LogAnalyzerAgent の結果として要約する。

## 7. 共有メモリ更新

- shared/context.md には、ログ形式判定結果、例外検出、異常兆候の要約のみを記録する
- working.md には、候補ログの比較や未採用ファイルの検討メモを保持する

## 8. plan / action 差分

- plan モード: どのログを見に行くか、どの形式を想定するか、どの検索観点を使うかを返す
- action モード: 実際に detect_log_format を呼び出して検索し、要約結果を返す

## 9. 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/log_analyzer_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/log_analyzer_agent.py) の build_log_analyzer_agent_definition に残す
- 実処理は LogAnalyzerPhaseExecutor に集約し、Supervisor から直接呼べる形にする
- ログ形式判定は builtin の detect_log_format_and_search に寄せ、LogAnalyzer 側では対象選定と要約化に集中する

## 10. 未決事項

- 複数ログファイルをどう優先順位付けするか
- 生成した正規表現をそのまま共有メモリへ残すかどうか
- run_python_analysis をどの条件で併用するか