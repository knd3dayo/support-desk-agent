# support-ope-agents

Deep Agents と LangGraph を組み合わせて、カスタマーサポート業務をオーケストレーションする PoC 実装です。

## コンセプト

- 業務プロセス全体は LangGraph のワークフローで制御する
- スーパーバイザーおよびサブエージェントは各々 DeepAgent として実装する
- エージェント間の情報共有と進捗共有は、ケース単位の共有メモリファイルで行う
- 各エージェントは役割別ツールを持ち、コンテキスト逼迫時は圧縮済みサマリへ退避する
- 指示ファイルを差し替えることで、業務手順の細部を後から拡張できる
- CLI に加えて API と MCP を追加できる構成を前提にする
- ケースごとに workspace を登録でき、artifact と evidence を分離管理する

## 初期構成

- [docs/customer-support-deepagents-design.md](docs/customer-support-deepagents-design.md): 実装設計書
- [config.yml](config.yml): 非秘匿設定
- [.env.example](.env.example): 秘匿設定テンプレート
- [src/support_ope_agents](src/support_ope_agents): アプリ本体
- [src/support_ope_agents/interfaces](src/support_ope_agents/interfaces): API/MCP インターフェース層
- [instructions](instructions): 共通指示と役割別指示

## 起動

依存関係を導入した後、次のコマンドでワークフロー定義を出力します。

```bash
python -m support_ope_agents.cli print-workflow --config config.yml
```

ケース単位の作業ディレクトリを初期化します。

```bash
python -m support_ope_agents.cli init-case --prompt "CASE-001 の調査を開始してください" --config config.yml
```

外部ワークスペースを紐付けて初期化することもできます。

```bash
python -m support_ope_agents.cli init-case --prompt "CASE-002 の調査を開始してください" --config config.yml --workspace-path /data/support/case-002
```

`case_id` を明示的に渡す必要はなく、入力文から解決を試み、見つからなければ自動採番します。

plan モードでは、SuperVisorAgent が問い合わせ内容から workflow をルーティングし、同一 trace_id で action に引き継げる実行計画を返します。

```bash
python -m support_ope_agents.cli plan "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --config config.yml
```

action モードでは、plan モードの trace_id を指定して同一 trace_id 上で処理を継続します。

```bash
python -m support_ope_agents.cli action "CASE-003 の仕様か不具合か切り分けてください" --workspace-path /data/support/case-003 --trace-id TRACE-xxxx --config config.yml
```

FastAPI 雛形も追加済みで、`trace_id` を継続識別子として plan/action を公開できます。

```bash
uvicorn support_ope_agents.interfaces.api:create_app --factory --host 127.0.0.1 --port 8000
```

MCP は最小アダプタとして `plan` と `action` ツールを公開し、どちらも `trace_id` を正式な継続キーとして扱います。

共通の built-in ツールとして、画像/PDF/Office の解析、Office→PDF 変換、PDF→画像変換、テキスト抽出、Zip 操作を各エージェントへ配布します。役割別ツールはその上に追加され、最終的に [config.yml](config.yml) の `tools.overrides` で `builtin` / `mcp` / `disabled` に差し替えできます。`tools.mcp_manifest_path` で単一の `mcp.json` を指定し、設定した server 名や tool 名が参照先に存在しない場合は、CLI / API / MCP いずれの起動経路でも fail fast で起動エラーになります。

```yaml
support_ope_agents:
	tools:
		mcp_manifest_path: ../ai-chat-util/app/ai-chat-util-mcp.json
		overrides:
			LogAnalyzerAgent:
				analyze_pdf_files:
					type: builtin
				read_log_file:
					type: mcp
					server: AIChatUtilLocal
					tool: analyze_files
				convert_office_files_to_pdf:
					type: disabled
```

現在の workflow ルーティング対象は次の 3 系統です。

- 仕様調査ワークフロー
- 障害調査ワークフロー
- 判定困難ワークフロー

## 今後の実装対象

- DeepAgent の task ツール経由でのサブエージェント起動
- LangGraph checkpointer を使った非同期 HITL
- Zendesk / Redmine / ナレッジベース接続
- ガバナンス層とトレース基盤の接続