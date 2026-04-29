# support-desk-agent sample

* このディレクトリは、support-desk-agent を実 LLM / 実 MCP 連携込みで試すためのサンプルです。
* ai-platform-poc チームが問合せ元の顧客、support-desk-agent が一次サポート窓口、ai-chat-util チームがバックサポートをイメージしており、
本sampleにより確実な回答を生成できるか？できない場合はai-chat-utilチームへのエスカレーション文書が作成可能か？を確かめることを目的としています。
* ここで発見された、support-desk-agentの不具合は、イシューとして残して、ソース改修に役立てます。

## 1. 含まれるもの

- [samples/support-desk-agent/config-sample.yml](/home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-sample.yml): sample 実装向けの設定例
- [samples/support-desk-agent/config-prodction.yml](/home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-prodction.yml): production 実装向けの設定例
- [samples/support-desk-agent/workspace-template](/home/user/source/repos/support-desk-agent/samples/support-desk-agent/workspace-template): workspace 配置例

## 2. 想定するナレッジ

この sample では次を InvestigateAgent の document source として扱います。

- ai-platform-poc の技術検証資料: /home/user/source/repos/ai-platform-poc
- ai-chat-util のソース: /home/user/source/repos/ai-chat-util
- LangChain ドキュメント: /home/user/oss/langchain-ai/langchain

## 3. 使い方

1. workspace テンプレートを任意の作業ディレクトリへコピーする
2. `.evidence/` 配下へ pytest 出力、調査メモ、エラーログを置く
3. sample_prompt.txt をそのまま使うか、問い合わせ文面を調整する
4. OpenAI API キーと、GitHub の external / internal issue を引ける MCP 環境を用意する
5. sample config を指定して action を実行する

API と React UI を使って試す場合は、このディレクトリに追加した起動スクリプトを使えます。

```bash
/home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample.sh \
  --workspace-root /tmp/support-desk-agent-sample-cases
```

この統合スクリプトは sample 用 API と React frontend をまとめて起動します。`--workspace-root` または環境変数 `SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT` が必須で、未指定ならエラー終了します。指定したディレクトリが存在しない場合は自動作成します。終了するときはその端末で `Ctrl+C` を押すと、子プロセスもあわせて停止します。

```bash
/home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample-react.sh
```

API だけ個別に起動したい場合は `start-sample-api.sh`、React だけ個別に起動したい場合は `start-sample-react.sh` も引き続き使えます。API 起動スクリプトは `--workspace-root` または `SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT` を必須とし、指定したディレクトリをケース作成先として使ったうえで、内部的には `uv run -m support_desk_agent.interfaces.api` を呼び出します。sample API は UI テストを優先して、既定では起動時の LLM probe を skip します。実 backend の疎通確認も startup で行いたい場合は `SUPPORT_OPE_SKIP_LLM_STARTUP_PROBE=0` を付けて起動してください。React 起動スクリプトはリポジトリ直下の frontend を開発モードで起動し、`API_PORT` が指定されていればそのポートの API を proxy します。

sample API 起動スクリプトは sibling の ai-chat-util ソース `/home/user/source/repos/ai-chat-util/app/src` を `PYTHONPATH` の先頭へ追加します。`uv sync -U` を実行しても、ローカル directory dependency が non-editable install のまま同じ version だと site-packages 側の古いビルドを掴み続けることがあるためです。sample 実行では source tree を優先し、support-desk-agent と ai-chat-util を同時開発している状態でも `AnalysisService` の最新 API を使います。

起動時に `--config` を省略すると `config.yml` を見にいくため、通常は `--config config-sample.yml` または `--config config-prodction.yml` を明示指定してください。

sample config で MCP manifest が未設定の場合、API 起動スクリプトは UI テストを止めないためにチケット MCP lookup を実行しないまま起動します。実 MCP 連携を含めて試したい場合は、sample config の `tools.mcp_manifest_path` を有効化するか、起動時に `MCP_MANIFEST_PATH=/path/to/manifest.json` を渡してください。GitHub MCP を使う場合は、manifest 側で `github` server を定義し、`GITHUB_PERSONAL_ACCESS_TOKEN` を環境変数で渡してください。

ポートを変えたい場合は環境変数で上書きできます。

```bash
API_PORT=8010 UI_PORT=5174 \
  /home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample.sh \
  --workspace-root /tmp/support-desk-agent-sample-cases \
  --config /home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-sample.yml
```

```bash
MCP_MANIFEST_PATH=/path/to/mcp-manifest.json \
  SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT=/tmp/support-desk-agent-sample-cases \
  /home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample.sh \
  --config /home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-sample.yml
```

```bash
SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT=/tmp/support-desk-agent-sample-cases \
  /home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample-api.sh \
  --config /home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-sample.yml
```

```bash
HOST=0.0.0.0 PORT=5174 /home/user/source/repos/support-desk-agent/samples/support-desk-agent/start-sample-react.sh
```

実行例:

```bash
python -m support_desk_agent.cli action \
  "ai-chat-util の利用方法について問い合わせがあります。関連資料を調査し、必要に応じてバックサポート向け問い合わせ文も作成してください。" \
  --workspace-path /tmp/support-desk-agent-support-case \
  --external-ticket-id 101 \
  --internal-ticket-id 202 \
  --config /home/user/source/repos/support-desk-agent/samples/support-desk-agent/config-sample.yml
```

ticket ID を省略した場合、外部・内部チケット ID は空のままとなり、IntakeAgent の MCP lookup はスキップします。GitHub MCP を使う sample config では、チケット文脈を取得したい場合に `--external-ticket-id` と `--internal-ticket-id` へ config に設定した各 repository の GitHub Issue 番号を指定してください。

## 4. 補足

- この sample は実 LLM / 実 MCP 前提です。`LLM_API_KEY` と、sample config の `github` server を解決できる MCP 実行環境を事前に用意してください
- sample config の `tools.ticket_sources.external.arguments.repo` と `tools.ticket_sources.internal.arguments.repo` に、利用する GitHub repository を設定してください
- LangChain ドキュメントの path は `/home/user/oss/langchain-ai/langchain` を前提にしています
- sample config は `constraint_mode: default` を既定にしています。`instruction_only` は instruction 側の制御だけが残るため、sample では回答や再調査の誘導が強く見えることがあります。
- `InvestigateAgent.result_mode: raw_backend` は取得 payload の詳細度を上げる設定です。制約の強さを変えたい場合は `constraint_mode` を agent ごとに調整してください。
- sample config は既定で `model: poc-chat-model` と `base_url: http://localhost:4000` を使います。local LiteLLM を経由せず直接 OpenAI 互換 API を使いたい場合は、起動時に `SUPPORT_OPE_LLM_MODEL=gpt-4.1 SUPPORT_OPE_LLM_BASE_URL=` のように上書きできます。