# external_ticket

## 1. 目的

顧客向け外部チケット情報を取得し、既知事例や現状把握に使う。

## 2. 利用エージェント

- IntakeAgent
- KnowledgeRetrieverAgent

## 3. 既定実装 / 接続点

- 論理ツール名: external_ticket
- 既定では未接続で、MCP override または [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の intake.external_ticket で構成する
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- IntakeAgent では、明示 external_ticket_id が与えられた場合の初期 hydration に使う
- KnowledgeRetrieverAgent では、workspace 取り込み済み情報で不足する場合の再取得に使う

## 4. MCP 契約

推奨する返却 JSON は次の形とする。

```json
{
	"ticket_id": "EXT-123",
	"summary": "チケットの要約",
	"title": "件名",
	"description": "本文や詳細",
	"attachments": [
		{
			"filename": "application.log",
			"content_base64": "..."
		},
		{
			"filename": "context.txt",
			"content": "添付本文"
		}
	]
}
```

- 入力は ticket_id を受け取る
- attachments は省略可能
- 添付は content_base64、content、path のいずれかを持つことを推奨する
- IntakeAgent はこの JSON を .artifacts/intake/ 配下へ保存し、後続 agent が再利用する

## 5. 実装状況

- 既定実装なし