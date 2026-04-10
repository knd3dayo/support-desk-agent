# 共通設計

## 1. 目的

本書は [docs/customer-support-deepagents-design.md](/home/user/source/repos/support-ope-agents/docs/customer-support-deepagents-design.md) を補完し、各エージェント詳細設計で共通に参照する前提と記述ルールを定義する。
全体アーキテクチャ、責務分離、ワークフロー上の位置付けは親設計書に従い、本書では agent 個別仕様の共通観点と shared memory 設計を定義する。

## 2. 文書の使い方

- 親設計書: 全体構成、フェーズ分割、共通方針を定義する
- 本書: agent 個別設計で共通に使う観点と shared memory 設計を定義する
- agent 個別仕様: [docs/agents/supervisor-agent.md](/home/user/source/repos/support-ope-agents/docs/agents/supervisor-agent.md)、[docs/agents/intake-agent.md](/home/user/source/repos/support-ope-agents/docs/agents/intake-agent.md) を参照する
- tool 個別仕様: [docs/tools/README.md](/home/user/source/repos/support-ope-agents/docs/tools/README.md) を参照する

各 agent 文書では次の観点をそろえる。

- 役割
- 呼び出し元 / 呼び出し先
- 入力
- 出力
- 使用ツールへの参照
- 共有メモリ更新
- plan / action 差分
- 実装方針
- 未決事項

## 3. 共有メモリ Payload

write_shared_memory の既定実装は、文字列だけでなく構造化 payload を受け付ける。
構造化 payload を使う場合の基本スキーマは次のとおり。

- title: Markdown 見出しとして出力するタイトル
- heading_level: title を何段階の見出しで出力するか。省略時は 1
- summary: 箇条書きの前に置く短い要約文
- bullets: フラットな箇条書きとして出力する配列
- sections: セクション配列。各要素は title、summary、bullets を持てる

例:

```json
{
   "title": "Shared Context",
   "heading_level": 1,
   "bullets": [
      "Case ID: CASE-001",
      "Trace ID: TRACE-001"
   ],
   "sections": [
      {
         "title": "Intake Summary",
         "bullets": [
            "Category: incident_investigation",
            "Urgency: high"
         ]
      }
   ]
}
```

既定実装ではこの payload を Markdown へ整形し、shared/context.md、shared/progress.md、shared/summary.md のいずれかへ replace または append で反映する。
実装上は [src/support_ope_agents/tools/shared_memory_payload.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/shared_memory_payload.py) に型を定義し、dict の自由記述を減らす。