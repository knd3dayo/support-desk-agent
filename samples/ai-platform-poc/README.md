# ai-platform-poc 向け sample

* このディレクトリは、ai-platform-poc チームが support-ope-agents を実 LLM / 実 MCP 連携込みで試すためのサンプルです。
* ai-platform-poc チームが問合せ元の顧客、sampleが一次サポート窓口、ai-chat-utilチームがバックサポートをイメージしており、
本sampleにより確実な回答を生成できるか？できない場合はai-chat-utilチームへのエスカレーション文書が作成可能か？を確かめることを目的としています。
* ここで発見された、support-ope-agentsの不具合は、イシューとして残して、ソース改修に役立てます。

## 1. 含まれるもの

- [samples/ai-platform-poc/config.yml](/home/user/source/repos/support-ope-agents/samples/ai-platform-poc/config.yml): ai-platform-poc 向けの設定例
- [samples/ai-platform-poc/sample_prompt.txt](/home/user/source/repos/support-ope-agents/samples/ai-platform-poc/sample_prompt.txt): 問い合わせ文面の例
- [samples/ai-platform-poc/workspace-template](/home/user/source/repos/support-ope-agents/samples/ai-platform-poc/workspace-template): workspace 配置例

## 2. 想定するナレッジ

この sample では次を KnowledgeRetrieverAgent の document source として扱います。

- ai-platform-poc の技術検証資料: /home/user/source/repos/ai-platform-poc
- ai-chat-util のソース: /home/user/source/repos/ai-chat-util
- LangChain ドキュメント: /home/user/oss/langchain-ai/langchain

## 3. 使い方

1. workspace テンプレートを任意の作業ディレクトリへコピーする
2. `.evidence/` 配下へ pytest 出力、調査メモ、エラーログを置く
3. sample_prompt.txt をそのまま使うか、問い合わせ文面を調整する
4. OpenAI API キーと、external / internal ticket を引ける MCP 環境を用意する
5. sample config を指定して action を実行する

実行例:

```bash
python -m support_ope_agents.cli action \
  "$(cat /home/user/source/repos/support-ope-agents/samples/ai-platform-poc/sample_prompt.txt)" \
  --workspace-path /tmp/ai-platform-poc-support-case \
  --external-ticket-id EXT-A-02-02 \
  --internal-ticket-id INT-A-02-02 \
  --config /home/user/source/repos/support-ope-agents/samples/ai-platform-poc/config.yml
```

ticket ID を省略した場合は trace_id から `EXT-TRACE-...` と `INT-TRACE-...` が自動生成されます。ただしこの自動採番 ID は trace 相関用であり、KnowledgeRetrieverAgent は external / internal ticket の実参照をスキップします。実チケットを引きたい場合は `--external-ticket-id` と `--internal-ticket-id` を明示指定してください。

## 4. 補足

- この sample は実 LLM / 実 MCP 前提です。`OPENAI_API_KEY` と、sample config の `support-ticket-mcp` を解決できる MCP 実行環境を事前に用意してください
- ai-chat-util 側に MCP manifest がある場合は、sample config の `tools.mcp_manifest_path` と `tools.logical_tools.*` を環境に合わせて有効化してください
- LangChain ドキュメントの path は `/home/user/oss/langchain-ai/langchain` を前提にしています