# support-ope-agents

Deep Agents と LangGraph を組み合わせて、カスタマーサポート業務をオーケストレーションする PoC 実装です。

## コンセプト

- 業務プロセス全体は LangGraph のワークフローで制御する
- スーパーバイザーおよびサブエージェントは各々 DeepAgentまたはLangGraphのサブグラフとして実装する
- エージェント間の情報共有と進捗共有は、ケース単位の共有メモリファイルで行う
- ObjectiveEvaluator が客観基準で評価するレポートを生成
- 各エージェントは役割別ツールを持ち、コンテキスト逼迫時は圧縮済みサマリへ退避する
- 指示ファイルを差し替えることで、業務手順の細部を後から拡張できる
- CLI に加えて API と MCP を追加できる構成を前提にする
- ケースごとに workspace を登録でき、artifact と evidence を分離管理する
- I/F(API/MCP/CLI) -> Runtime -> Workflow -> 各種エージェント -> ツールという構造を持ち、それぞれ以下の役割を持つ
  - I/F
  - Runtime
  - Workflow
  - 各種エージェント
  - ツール

## 初期構成

- [docs/customer-support-deepagents-design.md](docs/customer-support-deepagents-design.md): 実装設計書
- [docs/configuration.md](docs/configuration.md): 設定ガイド
- [config.yml](config.yml): 非秘匿設定
- [.env.example](.env.example): 秘匿設定テンプレート
- [src/support_ope_agents](src/support_ope_agents): アプリ本体
- [src/support_ope_agents/interfaces](src/support_ope_agents/interfaces): API/MCP インターフェース層
- [src/support_ope_agents/instructions/defaults](src/support_ope_agents/instructions/defaults): 共通指示と役割別指示の内蔵デフォルト
- [.instructions](.instructions): 必要に応じて既定指示を上書きするための任意 override ディレクトリ

## runtime mode の考え方

このリポジトリには `sample` 系と `production` 系の 2 系統の runtime 実装があります。どちらを使うかは [config.yml](config.yml) の `support_ope_agents.runtime.mode` で切り替えます。

```yaml
support_ope_agents:
	runtime:
		mode: production
```

`sample` 系は、汎用的な作り込みを主目的にせず、コンセプト確認と UI / フローのテストを素早く回すための簡素な実装です。PoC の流れを短く確認したい場合、画面やケース進行のたたき台を試したい場合、個別の制約や例外処理をまだ詰め切っていない段階で全体像を確認したい場合に向いています。サンプル環境の起動例や前提条件は [samples/support-ope-agents/README.md](samples/support-ope-agents/README.md) を参照してください。

`production` 系は、通常運用を見据えて、より多くの状況を想定した例外処理、制約、状態遷移、外部連携を含めるための実装です。`sample` で確認したコンセプトをそのまま終わらせず、実際の業務ワークフローに近い条件へ具体化していくことを目的にしています。既定の [config.yml](config.yml) はこちらを前提にしており、CLI / API / MCP の説明も原則として production runtime を基準にしています。

使い分けの目安は次のとおりです。

- まず画面や基本フローを早く確認したい場合は `sample`
- 例外処理、承認、再開、チェックポイント、レポート生成まで含めて挙動を詰めたい場合は `production`
- 実運用に近い設定やテストを増やしていく場合は `production` を基準にし、`sample` は概念実証や比較対象として扱う

README 中の通常の起動例は `production` 前提です。`sample` を使う場合は [samples/support-ope-agents/config-sample.yml](samples/support-ope-agents/config-sample.yml) のように `runtime.mode: sample` を持つ設定ファイルを指定して起動します。

## 起動

依存関係を導入した後、次のコマンドでワークフロー定義を出力します。

```bash
python -m support_ope_agents.cli print-workflow --config config.yml
```

ケース単位の作業ディレクトリを初期化します。

```bash
python -m support_ope_agents.cli init-case --prompt "CASE-001 の調査を開始してください" --workspace-path /data/support/case-001 --config config.yml
```

指定した workspace が、そのケースの実体ディレクトリとして使われます。`.memory`、`.artifacts`、`.evidence`、`.report`、`.traces/checkpoints.sqlite` などの管理用ファイルもこの workspace 配下に作られます。

```bash
python -m support_ope_agents.cli init-case --prompt "CASE-002 の調査を開始してください" --config config.yml --workspace-path /data/support/case-002
```

`case_id` を明示的に渡す必要はなく、入力文から解決を試み、見つからなければ自動採番します。workspace 配下には `.support-ope-case-id` が作成され、次回以降はそのファイルから同じ case_id を再解決できます。

plan モードでは、SuperVisorAgent が問い合わせ内容から workflow をルーティングし、同一 trace_id で action に引き継げる実行計画を返します。

```bash
python -m support_ope_agents.cli plan "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --config config.yml
```

action モードでは、plan モードの trace_id を指定して同一 trace_id 上で処理を継続します。

```bash
python -m support_ope_agents.cli action "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --trace-id TRACE-xxxx --config config.yml
```

workspace 配下の SQLite checkpointer の状態は次のコマンドで確認できます。

```bash
python -m support_ope_agents.cli checkpoint-status --case-id CASE-003 --workspace-path /data/support/case-003 --trace-id TRACE-xxxx --config config.yml
```

改善レポートは明示的に generate-report で作成できるほか、[config.yml](config.yml) の `agents.SuperVisorAgent.auto_generate_report` を true にすると action / resume 実行後に自動生成できます。出力先は `data_paths.report_subdir` で、既定では workspace 配下の `.report/support-improvement-<trace_id>.md` です。

改善レポートの評価主体は `ObjectiveEvaluator` です。レポートには全体シーケンス図に加え、IntakeAgent や Draft Review ループなどのサブグラフ詳細シーケンス、`.memory/shared` と各 agent working memory の情報伝達監査、エージェント別点数が含まれます。評価ルールの閾値や減点値は `agents.ObjectiveEvaluator` で調整できます。

plan モードでは改善レポートは自動生成しません。plan は実行前の計画結果であり、実際にどの agent が何を呼び、どの調査結果で承認待ちやクローズに到達したかという評価材料が不足するためです。

FastAPI 雛形も追加済みで、`trace_id` を継続識別子として plan/action を公開できます。

```bash
uv run -m support_ope_agents.interfaces.api
```

React + Vite ベースの SPA も追加済みで、ケース一覧、チャット会話、ファイルアップロード、ワークスペースツリー、ZIP ダウンロードを 1 画面で扱えます。開発時は frontend 側を別起動し、本番相当では build した `frontend/dist` を FastAPI が同居配信します。

```bash
cd frontend
npm install
npm run build
```

開発用のホットリロードを使う場合は、別端末で次を実行します。

```bash
cd frontend
npm run dev
```

このとき API 側は既定で `0.0.0.0:8000` に bind するため、先に FastAPI を起動しておきます。SPA からは次の UI 向け API を利用します。

```bash
uv run -m support_ope_agents.interfaces.api
```

軽量認証を付ける場合は [config.yml](config.yml) の `interfaces.auth_required` を true にし、`interfaces.auth_token` は `os.environ/SUPPORT_OPE_API_TOKEN` のように環境変数参照で設定します。開発中に frontend dev server を別 origin で開く場合は、`interfaces.cors_allowed_origins` に `http://127.0.0.1:5173` を追加してください。フロント画面右上の Auth Token 欄に同じトークンを保存すると、以後は `Authorization: Bearer <token>` を自動送信します。

ワークスペースプレビューは、テキストに加えて画像と PDF のインライン表示にも対応しています。画像/PDF 以外のバイナリは従来どおり別ウィンドウ表示を使います。

- `GET /cases`: ケース一覧
- `POST /cases`: 既定の `work/cases` 配下に新規ケースを初期化
- `GET /cases/{case_id}/history`: 会話履歴取得
- `GET /cases/{case_id}/workspace`: ファイルツリー取得
- `GET /cases/{case_id}/workspace/file`: テキストプレビュー取得
- `POST /cases/{case_id}/workspace/upload`: ケース workspace へファイル保存
- `GET /cases/{case_id}/workspace/download`: ケース workspace の ZIP ダウンロード

MCP は最小アダプタとして `plan` と `action` ツールを公開し、どちらも `trace_id` を正式な継続キーとして扱います。

共通の built-in ツールとして、画像/PDF/Office の解析、Office→PDF 変換、PDF→画像変換、テキスト抽出、Zip 操作を各エージェントへ配布します。役割別ツールはその上に追加され、最終的に [config.yml](config.yml) の `tools.logical_tools` で `enabled` と `provider: builtin | mcp` を切り替えます。`provider: mcp` を使う logical tool が 1 つでもあれば `tools.mcp_manifest_path` が必須で、設定した server 名や tool 名が参照先に存在しない場合は、CLI / API / MCP いずれの起動経路でも fail fast で起動エラーになります。

KnowledgeRetrieverAgent と ComplianceReviewerAgent については、[config.yml](config.yml) の `document_sources` に定義した複数の文書ソースを DeepAgents の `CompositeBackend` でまとめて扱います。各 source は `/knowledge/<source_name>/` または `/policy/<source_name>/` に route され、各 tool は 1 つの backend から複数文書ソースを `read` / `glob` / `grep` できます。検索結果の組み立ては caller 側で行い、`summary` には生成要約ではなく該当 Markdown からの raw snippet を保持します。KnowledgeRetrieverAgent の working memory には source ごとの raw result も残します。`external_ticket` と `internal_ticket` は `tools.logical_tools.external_ticket` / `internal_ticket` で provider を定義し、MCP 利用時は起動時に binding を検証します。

仕様問い合わせでは、fallback classification が `specification_inquiry` を優先し、KnowledgeRetrieverAgent は問い合わせ文中に明示された source 名を優先します。DraftWriterAgent は取得した feature bullets と Markdown 形式の根拠リンクを使い、内部エージェント名や内部レビュー文言を含まない顧客向けドラフトを生成します。

instruction は src 内にデフォルトを同梱しているため、最初に動かすだけであれば .instructions の準備は不要です。必要になった時だけ [config.yml](config.yml) の `config_paths.instructions_path` で外部ディレクトリを指定し、共通指示や役割別指示を override できます。

共通 instruction の `common.md` は全エージェントに前置で適用されます。既定では、処理開始時に shared memory と自エージェントの working memory を必ず確認するルールをここへ置いています。

```yaml
support_ope_agents:
	agents:
		KnowledgeRetrieverAgent:
			document_sources:
				- name: ai-platform-poc
				  description: 生成AI基盤の設計資料
				  path: /home/user/source/repos/ai-platform-poc
	tools:
		mcp_manifest_path: ../ai-chat-util/app/ai-chat-util-mcp.json
		logical_tools:
			read_log_file:
				enabled: true
				provider: mcp
				server: AIChatUtilLocal
				tool: analyze_files
			run_python_analysis:
				enabled: false
```

現在の workflow ルーティング対象は次の 3 系統です。

- 仕様調査ワークフロー
- 障害調査ワークフロー
- 判定困難ワークフロー

## 今後の実装対象

- DeepAgent の task ツール経由でのサブエージェント起動
- Approval interrupt の再開 UX 改善
- Zendesk / Redmine / ナレッジベース接続
- ガバナンス層とトレース基盤の接続