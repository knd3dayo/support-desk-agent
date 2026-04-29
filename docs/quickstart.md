# Quickstart

support-ope-agents を最初に動かすための実行手順です。ここでは production runtime を前提に、CLI、API、frontend、MCP 連携までの起動導線をまとめます。

sample runtime を使って PoC の流れを素早く確認したい場合は [../samples/support-ope-agents/README.md](../samples/support-ope-agents/README.md) と [../samples/support-ope-agents/config-sample.yml](../samples/support-ope-agents/config-sample.yml) を参照してください。

## 前提

- 依存関係の導入と設定ファイルの準備が完了していること
- 通常の起動例は [../config.yml](../config.yml) を使う production runtime 前提であること
- 設定項目の詳細は [configuration.md](configuration.md) を参照すること

## CLI でワークフローを確認する

依存関係を導入した後、次のコマンドでワークフロー定義を出力します。

```bash
python -m support_desk_agent.cli print-workflow --config config.yml
```

## ケース workspace を初期化する

ケース単位の作業ディレクトリを初期化します。

```bash
python -m support_desk_agent.cli init-case --prompt "CASE-001 の調査を開始してください" --workspace-path /data/support/case-001 --config config.yml
```

指定した workspace が、そのケースの実体ディレクトリとして使われます。`.memory`、`.artifacts`、`.evidence`、`.report`、`.traces/checkpoints.sqlite` などの管理用ファイルもこの workspace 配下に作られます。

```bash
python -m support_desk_agent.cli init-case --prompt "CASE-002 の調査を開始してください" --config config.yml --workspace-path /data/support/case-002
```

`case_id` を明示的に渡す必要はなく、入力文から解決を試み、見つからなければ自動採番します。workspace 配下には `.support-ope-case-id` が作成され、次回以降はそのファイルから同じ case_id を再解決できます。

## plan と action を実行する

plan モードでは、SuperVisorAgent が問い合わせ内容から workflow をルーティングし、同一 trace_id で action に引き継げる実行計画を返します。

```bash
python -m support_desk_agent.cli plan "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --config config.yml
```

action モードでは、plan モードの trace_id を指定して同一 trace_id 上で処理を継続します。

```bash
python -m support_desk_agent.cli action "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --trace-id TRACE-xxxx --config config.yml
```

workspace 配下の SQLite checkpointer の状態は次のコマンドで確認できます。

```bash
python -m support_desk_agent.cli checkpoint-status --case-id CASE-003 --workspace-path /data/support/case-003 --trace-id TRACE-xxxx --config config.yml
```

## 改善レポート

改善レポートは明示的に generate-report で作成できるほか、[../config.yml](../config.yml) の `agents.SuperVisorAgent.auto_generate_report` を true にすると action / resume 実行後に自動生成できます。出力先は `data_paths.report_subdir` で、既定では workspace 配下の `.report/support-improvement-<trace_id>.md` です。

改善レポートの評価主体は `ObjectiveEvaluator` です。レポートには全体シーケンス図に加え、IntakeAgent や Draft Review ループなどのサブグラフ詳細シーケンス、`.memory/shared` と各 agent working memory の情報伝達監査、エージェント別点数が含まれます。評価ルールの閾値や減点値は `agents.ObjectiveEvaluator` で調整できます。

plan モードでは改善レポートは自動生成しません。plan は実行前の計画結果であり、実際にどの agent が何を呼び、どの調査結果で承認待ちやクローズに到達したかという評価材料が不足するためです。

## API を起動する

FastAPI 雛形も追加済みで、`trace_id` を継続識別子として plan と action を公開できます。

```bash
uv run -m support_desk_agent.interfaces.api
```

UI 向け API は次のとおりです。

- `GET /cases`: ケース一覧
- `POST /cases`: 既定の `work/cases` 配下に新規ケースを初期化
- `GET /cases/{case_id}/history`: 会話履歴取得
- `GET /cases/{case_id}/workspace`: ファイルツリー取得
- `GET /cases/{case_id}/workspace/file`: テキストプレビュー取得
- `POST /cases/{case_id}/workspace/upload`: ケース workspace へファイル保存
- `GET /cases/{case_id}/workspace/download`: ケース workspace の ZIP ダウンロード

軽量認証を付ける場合は [../config.yml](../config.yml) の `interfaces.auth_required` を true にし、`interfaces.auth_token` は `os.environ/SUPPORT_OPE_API_TOKEN` のように環境変数参照で設定します。frontend dev server を別 origin で開く場合は、`interfaces.cors_allowed_origins` に `http://127.0.0.1:5173` を追加してください。フロント画面右上の Auth Token 欄に同じトークンを保存すると、以後は `Authorization: Bearer <token>` を自動送信します。

## frontend を起動する

React + Vite ベースの SPA も追加済みで、ケース一覧、チャット会話、ファイルアップロード、ワークスペースツリー、ZIP ダウンロードを 1 画面で扱えます。本番相当では build した `frontend/dist` を FastAPI が同居配信します。

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

このとき API 側は既定で `0.0.0.0:8000` に bind するため、先に FastAPI を起動しておきます。

ワークスペースプレビューは、テキストに加えて画像と PDF のインライン表示にも対応しています。画像と PDF 以外のバイナリは従来どおり別ウィンドウ表示を使います。

## MCP とツール連携

MCP は最小アダプタとして `plan` と `action` ツールを公開し、どちらも `trace_id` を正式な継続キーとして扱います。

共通の built-in ツールとして、画像、PDF、Office の解析、Office から PDF への変換、PDF から画像への変換、テキスト抽出、Zip 操作を各エージェントへ配布します。役割別ツールはその上に追加され、最終的に [../config.yml](../config.yml) の `tools.logical_tools` で `enabled` と `provider: builtin | mcp` を切り替えます。`provider: mcp` を使う logical tool が 1 つでもあれば `tools.mcp_manifest_path` が必須で、設定した server 名や tool 名が参照先に存在しない場合は、CLI、API、MCP いずれの起動経路でも fail fast で起動エラーになります。

KnowledgeRetrieverAgent と ComplianceReviewerAgent については、[../config.yml](../config.yml) の `document_sources` に定義した複数の文書ソースを DeepAgents の `CompositeBackend` でまとめて扱います。各 source は `/knowledge/<source_name>/` または `/policy/<source_name>/` に route され、各 tool は 1 つの backend から複数文書ソースを `read`、`glob`、`grep` できます。検索結果の組み立ては caller 側で行い、`summary` には生成要約ではなく該当 Markdown からの raw snippet を保持します。KnowledgeRetrieverAgent の working memory には source ごとの raw result も残します。`external_ticket` と `internal_ticket` は `tools.logical_tools.external_ticket` と `internal_ticket` で provider を定義し、MCP 利用時は起動時に binding を検証します。

仕様問い合わせでは、fallback classification が `specification_inquiry` を優先し、KnowledgeRetrieverAgent は問い合わせ文中に明示された source 名を優先します。DraftWriterAgent は取得した feature bullets と Markdown 形式の根拠リンクを使い、内部エージェント名や内部レビュー文言を含まない顧客向けドラフトを生成します。

instruction は src 内にデフォルトを同梱しているため、最初に動かすだけであれば .instructions の準備は不要です。必要になった時だけ [../config.yml](../config.yml) の `config_paths.instructions_path` で外部ディレクトリを指定し、共通指示や役割別指示を override できます。

共通 instruction の `common.md` は全エージェントに前置で適用されます。既定では、処理開始時に shared memory と自エージェントの working memory を必ず確認するルールをここへ置いています。

```yaml
support_desk_agent:
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
