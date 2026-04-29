# external_ticket

## 1. 目的

顧客向け外部チケット情報を取得し、既知事例や現状把握に使う。

## 2. 利用エージェント

- IntakeAgent
- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: external_ticket
- 既定では未接続で、[config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.ticket_sources.external で接続先を構成する
- ToolRegistry 定義: [src/support_desk_agent/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/tools/registry.py)
- IntakeAgent では、明示 external_ticket_id が与えられた場合の初期 hydration に使う
- InvestigateAgent では、workspace 取り込み済み情報で不足する場合の再取得に使う
- tools.logical_tools.external_ticket は廃止済みで、設定しても validation error になる

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
- 接続先の MCP server 名や固定引数は tools.ticket_sources.external に置く
- attachments は省略可能
- 添付は content_base64、content、path のいずれかを持つことを推奨する
- IntakeAgent はこの JSON を .artifacts/intake/ 配下へ保存し、後続 agent が再利用する

## 5. 実装状況

- 区分: integration-required
- 既定実装なし
- tools.ticket_sources.external の接続先構成が前提