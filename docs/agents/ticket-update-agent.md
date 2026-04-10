# TicketUpdateAgent 詳細設計

## 1. 役割

TicketUpdateAgent は承認後に外部チケット更新内容を確定し、Zendesk / Redmine などへの反映を段階的に実施する疑似エージェントである。
更新前には必ず HITL を挟み、人間が最終確認してから実行する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: ApprovalAgent の approve 分岐
- 呼び出し先: 外部チケット更新処理、完了後は CLOSED
- 接続先: 更新前 HITL で差戻しがあれば SuperVisorAgent 管理フェーズへ戻す

## 3. 入力

- draft_response
- ticket_update_payload の元になる回答内容
- case_id、trace_id
- 外部チケット識別情報

## 4. 出力

CaseState へ反映する主な出力:

- ticket_update_payload
- ticket_update_result
- status = CLOSED
- current_agent = TicketUpdateAgent
- next_action

共有メモリへ反映する主な出力:

- shared/progress.md: 更新準備完了、更新実行結果、差戻しの有無
- shared/summary.md: 最終的なクローズ結果の要約

## 5. 使用ツール

TicketUpdateAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/prepare_ticket_update.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/prepare_ticket_update.md)
- [docs/tools/specs/zendesk_reply.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/zendesk_reply.md)
- [docs/tools/specs/redmine_update.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/redmine_update.md)

## 6. 処理内容

1. 更新ペイロード準備
   draft_response をもとに外部チケット反映内容を組み立てる。
2. 更新前 HITL
   実更新前に人間が内容を確認し、承認または差戻しする。
3. 外部更新実行
   Zendesk / Redmine などに更新を反映する。
4. 終了処理
   結果を state と shared/progress.md に記録し、CLOSED へ遷移する。

## 7. 共有メモリ更新

- shared/progress.md には更新準備、更新待ち、更新完了を残す
- shared/summary.md にはクローズ時の最終結果を圧縮して残す

## 8. plan / action 差分

- plan モード: 更新対象と更新方針のみを返す
- action モード: 実際の更新ペイロードを生成し、HITL 後に外部更新を行う

## 9. 実装方針

- TicketUpdateAgent は LangGraph subgraph として実装し、prepare と execute を分離する
- 外部チケット更新は当面スタブ化し、後続で MCP または API adapter へ置き換える
- 更新前 HITL は ApprovalAgent とは別の停止点として扱う

## 10. 未決事項

- Zendesk / Redmine 以外の更新先拡張方針
- 更新差戻し時にどの state まで巻き戻すか
- 更新失敗時のリトライ・補償設計