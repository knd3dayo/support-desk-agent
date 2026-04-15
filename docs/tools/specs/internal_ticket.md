# internal_ticket

## 1. 目的

内部管理チケット情報を取得し、過去対応や保留論点を確認する。

## 2. 利用エージェント

- IntakeAgent
- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: internal_ticket
- 既定では未接続で、[config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.logical_tools.internal_ticket で構成する
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- IntakeAgent では、明示 internal_ticket_id が与えられた場合の初期 hydration に使う
- InvestigateAgent では、workspace 取り込み済み情報で不足する場合の再取得に使う

## 4. MCP 契約

推奨する返却 JSON は external_ticket と同じ構造とし、少なくとも次を含む。

```json
{
	"ticket_id": "INT-456",
	"summary": "内部チケットの要約",
	"attachments": [
		{
			"filename": "investigation-note.txt",
			"content": "調査メモ"
		}
	]
}
```

- 入力は ticket_id を受け取る
- 添付は content_base64、content、path のいずれかを持つことを推奨する
- IntakeAgent は保存した添付を .artifacts/intake/ 配下に置き、InvestigateAgent が優先参照する

## 5. 実装状況

- 既定実装なし