# LogAnalyzerAgent 詳細設計

## 1. 役割

LogAnalyzerAgent は調査フェーズでログ、添付証跡、ワークスペース情報から異常兆候と再現条件を抽出する専門エージェントである。
SuperVisorAgent の指示のもとでログ形式を見極め、必要に応じて ZIP / PDF / Excel / 画像などの非テキスト証跡を前処理し、例外、エラーレベル、時刻、再現条件に関わる手掛かりを整理する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation フェーズ
- 呼び出し先: 現時点ではなし。結果は SuperVisorAgent に返す
- 参照先: evidence、artifacts、shared/context.md、shared/progress.md、agent working memory

## 3. 入力

LogAnalyzerAgent が主要入力として扱うものは次のとおり。

- CaseState の raw_issue、intake_category、intake_urgency、intake_investigation_focus
- ケース workspace 配下の evidence / artifacts に置かれたログファイル、ZIP、PDF、Excel、画像などの調査用証跡
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

LogAnalyzerAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/analyze_pdf_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_pdf_files.md)
- [docs/tools/specs/analyze_office_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_office_files.md)
- [docs/tools/specs/analyze_image_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_image_files.md)
- [docs/tools/specs/extract_text_from_file.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/extract_text_from_file.md)
- [docs/tools/specs/list_zip_contents.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/list_zip_contents.md)
- [docs/tools/specs/extract_zip.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/extract_zip.md)
- [docs/tools/specs/convert_pdf_files_to_images.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/convert_pdf_files_to_images.md)
- [docs/tools/specs/detect_log_format.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/detect_log_format.md)
- [docs/tools/specs/read_log_file.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_log_file.md)
- [docs/tools/specs/run_python_analysis.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/run_python_analysis.md)
- [docs/tools/specs/write_working_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_working_memory.md)

## 6. 処理内容

LogAnalyzerAgent の処理は次の段階を基本とする。

1. 証跡種別判定
   evidence / artifacts から候補証跡を収集し、拡張子と内容からプレーンログ、ZIP、PDF、Office、画像を見分ける。
2. 前処理
   ZIP は一覧確認後に必要なら展開し、PDF / Office はテキスト抽出または要約、画像は画面キャプチャやエラーダイアログとして解析し、ログ解析に使える文字情報へ寄せる。
3. ログ形式推定
   抽出したテキストまたは対象ログの先頭 100 行前後から syslog / log4j / ISO 8601 / Java stack trace などの形式を推定する。
4. パターン生成と検索
   時刻、severity、例外名、スタックフレーム用の正規表現を生成し、ログ本文または抽出テキストを検索する。
5. 要約化
   扱った証跡種別、前処理結果、形式、主要一致件数、例外有無を LogAnalyzerAgent の結果として要約する。

## 7. 共有メモリ更新

- shared/context.md には、ログ形式判定結果、例外検出、異常兆候の要約のみを記録する
- working.md には、候補ログの比較や未採用ファイルの検討メモを保持する

## 8. plan / action 差分

- plan モード: どのログを見に行くか、どの形式を想定するか、どの検索観点を使うかを返す
- action モード: 実際に必要な前処理ツールと detect_log_format を呼び出して検索し、要約結果を返す

## 9. 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/log_analyzer_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/log_analyzer_agent.py) の build_log_analyzer_agent_definition に残す
- 実処理は LogAnalyzerPhaseExecutor に集約し、Supervisor から直接呼べる形にする
- 証跡の前処理は ToolRegistry が提供する builtin の analyze_pdf_files、analyze_office_files、analyze_image_files、extract_text_from_file、list_zip_contents、extract_zip などを優先利用する
- ログ形式判定は builtin の detect_log_format_and_search に寄せ、LogAnalyzer 側では対象選定、前処理オーケストレーション、要約化に集中する
- run_python_analysis の有効化と供給元は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.logical_tools.run_python_analysis で管理する
- logical_tools は enabled: false による無効化、provider: builtin による builtin 実装利用、provider: mcp による外部 MCP 利用の 3 パターンで扱う
- provider: mcp の場合は manifest と server / tool 定義を起動時に検証し、current builtin は未実装プレースホルダーとして扱う

## 10. 未決事項

- 複数ログファイルをどう優先順位付けするか
- 生成した正規表現をそのまま共有メモリへ残すかどうか
- run_python_analysis をどの条件で併用するか
- パスワード付き ZIP やスキャン PDF の扱いをどこまで既定対応に含めるか