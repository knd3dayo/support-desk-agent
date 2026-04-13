# 設定ガイド

## 1. 目的

本書は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の主要設定方針、とくに KnowledgeRetrieverAgent / ComplianceReviewerAgent の文書ソース、Agent 固有設定、論理ツール定義を説明する。

## 2. KnowledgeRetrieverAgent 設定

`agents.KnowledgeRetrieverAgent.document_sources` では、KnowledgeRetrieverAgent が参照する文書ソースを定義する。

- name: source を識別する論理名。backend 上では `/knowledge/<name>/` に対応する
- description: source の内容説明
- path: 実ファイルの格納先パス

`agents.KnowledgeRetrieverAgent.extraction_mode` では、DeepAgents にどの粒度で文書探索を依頼するかを指定する。

- relaxed: 既定値。DeepAgents に関連語も含めた広めの探索を依頼し、整形済みの要点を返す
- raw_backend: 診断向け。DeepAgents が選んだ主要文書の生テキストを追加 payload として保持する

例:

```yaml
support_ope_agents:
  agents:
    KnowledgeRetrieverAgent:
      extraction_mode: relaxed
      document_sources:
        - name: python312_manual
          description: Python 3.12 の公式仕様・標準ライブラリ資料
          path: ./docsources/python312_manual
        - name: growi_knowledge
          description: 社内 GROWI にエクスポートした運用ナレッジ
          path: ./docsources/growi_knowledge
        - name: ai-platform-poc
          description: 生成AI基盤のアーキテクチャ検討資料
          path: /home/user/source/repos/ai-platform-poc
```

## 3. DeepAgents backend との対応

- KnowledgeRetrieverAgent は `CompositeBackend` を使い、複数の document_sources を 1 つの backend に束ねる
- 各 source は `/knowledge/<source_name>/` に route する
- default backend は `StateBackend` とし、knowledge 以外の一時ファイルは state 側で扱う

KnowledgeRetrieverAgent の `search_documents` builtin は、検索判断そのものを DeepAgents に委ねる。support-ope-agents 側は backend mount、結果 payload の正規化、constraint_mode に応じた後段整形を担う。

検索結果 payload の組み立ては caller 側が担当する。`summary` には主に該当 Markdown からの raw snippet または DeepAgents が選んだ重要抜粋を入れる。

例:

- `/knowledge/python312_manual/` → `python312_manual.path`
- `/knowledge/growi_knowledge/` → `growi_knowledge.path`

ComplianceReviewerAgent でも同様に `CompositeBackend` を使い、各 source を `/policy/<source_name>/` に route する。

- `/policy/internal_policy/` → `internal_policy.path`
- `/policy/government_guidelines/` → `government_guidelines.path`

## 4. ComplianceReviewerAgent 設定

`agents.ComplianceReviewerAgent.document_sources` では、ポリシー確認時に参照する社内規定、政府ガイドライン、法令文書を定義する。

- name: source を識別する論理名。backend 上では `/policy/<name>/` に対応する
- description: source の内容説明
- path: 実ファイルの格納先パス

`agents.ComplianceReviewerAgent.ignore_patterns` と `agents.ComplianceReviewerAgent.ignore_patterns_file` では、ポリシー文書探索から除外するパスを指定する。

`agents.ComplianceReviewerAgent.notice` では、ドラフトに必須とする注意文ルールを定義する。

- required: true のとき注意文を必須化する
- required_phrases: いずれか 1 つ以上を含めば通過と判定する文言候補
- max_review_loops: DraftWriterAgent への再生成を何回まで自動で繰り返すか。既定値は 3

注意文設定は ComplianceReviewerAgent 側を正本とし、DraftWriterAgent はその設定を参照する。`required: false` が既定であり、その場合は注意文不足だけでは差戻しにしない。DraftWriterAgent 側へ同等設定は重複定義しない。

例:

```yaml
support_ope_agents:
  agents:
    ComplianceReviewerAgent:
      max_review_loops: 3
      ignore_patterns:
        - .*
        - '**/.*'
      ignore_patterns_file: ./.support-ope-policy-ignore
      document_sources:
        - name: internal_policy
          description: 社内回答ポリシー
          path: ./docsources/internal_policy
        - name: government_guidelines
          description: 政府ガイドライン
          path: ./docsources/government_guidelines
      notice:
        required: true
        required_phrases:
          - 生成AIは誤った回答をすることがあります
          - 生成AIは誤った回答を含む可能性があります
```

## 5. Agent 設定

全 Agent は共通で `constraint_mode` を持てる。加えて `agents.default_constraint_mode` を置くと、個別 Agent で `constraint_mode` を省略した場合の共通既定値として使える。

- `default`: 既定挙動。instruction と runtime 制約の両方を使う
- `instruction_only`: instruction だけを使い、コード側の制約は極力外す
- `runtime_only`: instruction を外し、コード側の制約だけを使う
- `bypass`: instruction と runtime 制約の両方を極力外す

`constraint_mode` は制約の適用方針であり、KnowledgeRetrieverAgent / ComplianceReviewerAgent の `extraction_mode` とは別物である。
`extraction_mode` は文書取得の詳細度を表し、KnowledgeRetrieverAgent では `relaxed / raw_backend` を使って DeepAgents の探索粒度と返却 payload を切り替える。

`agents.SuperVisorAgent.max_investigation_loops` では、Supervisor が新しい事実や知識を起点に LogAnalyzerAgent / KnowledgeRetrieverAgent へ再調査を出す回数を制御する。

- `0`: 追加調査ループを無効化する
- `1`: 初回調査後に新事実が見つかった場合のみ 1 回だけ再調査する
- `2` 以上: 追加で見つかった事実があれば、その回数まで再調査を続ける
- 既定値: `1`
- 上限: `5`

例:

```yaml
support_ope_agents:
  agents:
    default_constraint_mode: bypass
    SuperVisorAgent:
      constraint_mode: default
      max_investigation_loops: 2
    DraftWriterAgent:
      constraint_mode: runtime_only
    KnowledgeRetrieverAgent:
      extraction_mode: raw_backend
```

上の例では、未指定の Agent はすべて `bypass` を継承し、`SuperVisorAgent` と `DraftWriterAgent` だけ個別設定で override する。

`bypass` でも、破壊的な状態遷移や安全上必須の最小ガードまでは外さない。

### 5.x ランタイム制約のコード上の位置

ランタイム制約は設定だけで完結せず、コード上の複数箇所で実際の挙動に反映される。`Runtime constraint:` コメントで検索すると主要分岐を追える。

| 役割 | ファイル | 何を決めるか |
| --- | --- | --- |
| 制約の解決中枢 | `src/support_ope_agents/runtime/runtime_harness_manager.py` | `constraint_mode` から instruction / runtime / summary の各有効状態を解決する |
| instruction 抑止 | `src/support_ope_agents/instructions/loader.py` | `runtime_only` / `bypass` のとき role instruction を空文字にする |
| agent 生成時の反映 | `src/support_ope_agents/agents/deep_agent_factory.py` | resolved `constraint_mode` を instruction loader と agent 実行へ渡す |
| 可視化 | `src/support_ope_agents/runtime/control_catalog.py` | resolved mode と capability の on/off を control catalog に出す |
| DraftWriter のガード | `src/support_ope_agents/agents/draft_writer_agent.py` | 顧客向け sanitize と runtime guardrail の有効化を切り替える |
| KnowledgeRetriever の整形 | `src/support_ope_agents/agents/knowledge_retriever_agent.py` | 結果優先度付けと summary shaping の有効化を切り替える |
| ComplianceReviewer の review | `src/support_ope_agents/agents/compliance_reviewer_agent.py` | runtime review を実行するか、制約により省略するかを切り替える |
| Supervisor の runtime 分岐 | `src/support_ope_agents/agents/supervisor_agent.py` | 調査・レビュー周辺の runtime guardrail を切り替える |
| Intake の正規化 | `src/support_ope_agents/agents/intake_agent.py` | urgency の追加正規化を有効にするかを切り替える |

現在は `RuntimeHarnessManager` に mode 判定 helper を寄せており、各 agent は集合リテラルを直接持たず `RuntimeHarnessManager.runtime_constraints_enabled_for_mode()` などを使う。新しい制約分岐を追加するときは、この helper を使い、直上に `Runtime constraint:` コメントを付ける。

## 5.1 data_paths と checkpoint 保存先

`data_paths.trace_subdir` では、workspace 配下に作る LangGraph checkpoint 保存ディレクトリ名を指定する。既定値は `.traces` である。

`data_paths.checkpoint_db_filename` では、workspace 配下の `<trace_subdir>/` ディレクトリに作る LangGraph checkpointer 用 SQLite ファイル名を指定する。

- 既定値: `checkpoints.sqlite`
- 実際の保存先: `<workspace>/<trace_subdir>/<checkpoint_db_filename>`
- state の正本はこの SQLite checkpoint DB であり、trace ごとの JSON state は使わない

例:

```yaml
support_ope_agents:
  data_paths:
    trace_subdir: .traces
    checkpoint_db_filename: checkpoints.sqlite
```

`data_paths.report_subdir` では、改善レポートの出力ディレクトリ名を指定する。既定値は `.report` で、実際の出力先は `<workspace>/<report_subdir>/support-improvement-<trace_id>.md` になる。

`agents.SuperVisorAgent.auto_generate_report` を true にすると、Supervisor 実行結果に応じて改善レポートを自動生成する。

- `report_on: [waiting_approval]`: WAITING_APPROVAL 到達時に自動生成
- `report_on: [closed]`: CLOSED 到達時に自動生成
- `report_on: waiting_approval` のように単一文字列でも指定でき、その場合は 1 要素のリストとして扱う

plan モードでは自動生成しない。改善レポートは実行結果の評価を含むため、agent 呼び出し結果、採用ソース、ドラフトレビュー結果、承認待ちまたはクローズ到達後の状態が揃う action / resume 後にだけ生成する。

例:

```yaml
support_ope_agents:
  data_paths:
    report_subdir: .report
  agents:
    SuperVisorAgent:
      auto_generate_report: true
      report_on:
        - waiting_approval
```

エスカレーション判定語彙と不足資料補完の設定は `agents.BackSupportEscalationAgent.escalation` 配下に置く。BackSupportEscalationAgent を中心とした分岐の振る舞いをここで調整する。

`agents.IntakeAgent.pii_mask.enabled` では、IntakeAgent が PII マスキングを既定で実行するかを制御する。

- enabled: true のときのみ pii_mask を実行する
- 既定値: false
- Supervisor はこの設定を参照せず、PII マスクの実行有無は IntakeAgent 側でのみ判断する

例:

```yaml
support_ope_agents:
  agents:
    IntakeAgent:
      enabled: true
      auto_compress: true
      pii_mask:
        enabled: false
```

IntakeAgent は明示指定された external_ticket_id / internal_ticket_id があり、対応する MCP ツールが有効な場合に、ticket 情報と添付ファイルを case workspace 配下へ取り込む。
保存先の既定値は `.artifacts/intake/` とし、後続 agent はその投影結果を再利用する。

## 6. Tool 設定

`tools.logical_tools` では、IntakeAgent、KnowledgeRetrieverAgent、ComplianceReviewerAgent などが共有する各論理ツールの有効化と供給元を指定する。

- enabled: true なら利用対象、false なら無効化
- provider: builtin または mcp
- provider: mcp の場合は server と tool が必須
- provider: builtin の場合は必要に応じて builtin_tool で builtin 名を明示できる

- server: MCP manifest 上の server 名
- tool: 呼び出す tool 名
- description: source の説明

例:

```yaml
support_ope_agents:
  tools:
    mcp_manifest_path: ./mcp-manifest.json
    logical_tools:
      search_documents:
        enabled: true
        provider: builtin
      check_policy:
        enabled: true
        provider: builtin
      request_revision:
        enabled: true
        provider: builtin
      external_ticket:
        enabled: true
        provider: mcp
        description: 顧客向けケース管理システム
        server: support-ticket-mcp
        tool: get_external_ticket
      internal_ticket:
        enabled: true
        provider: mcp
        description: 内部管理用チケットシステム
        server: support-ticket-mcp
        tool: get_internal_ticket
```

external_ticket_id と internal_ticket_id は config.yml ではなく実行入力で与える。

- CLI: `plan` / `action` / `resume-customer-input` で `--external-ticket-id` と `--internal-ticket-id` を受け付ける
- API: 同名フィールドを request body で受け付ける
- 未指定時は trace_id から自動生成し、外部は `EXT-TRACE-...`、内部は `INT-TRACE-...` を使う

trace_id と ticket ID の関係を固定しておくことで、ケース実行単位の追跡と ticket source 照会の相関を取りやすくする。

### 6.1 MCP ツール I/O 契約

external_ticket / internal_ticket に対応する MCP ツールは、少なくとも次の I/O 契約を満たす前提とする。

- 入力: `ticket_id` を受け取る
- 出力: 指定 ID に対応するチケットの要約または詳細を文字列または JSON で返す
- 未取得時: 「not configured」ではなく、取得不可または未発見である旨が分かる応答を返す

推奨 JSON 例:

```json
{
  "ticket_id": "EXT-123",
  "summary": "チケット要約",
  "title": "件名",
  "description": "詳細本文",
  "attachments": [
    {
      "filename": "application.log",
      "content_base64": "..."
    },
    {
      "filename": "memo.txt",
      "content": "添付本文"
    },
    {
      "filename": "already-downloaded.pdf",
      "path": "/mounted/path/already-downloaded.pdf"
    }
  ]
}
```

- attachments は省略可能
- IntakeAgent は attachments を .artifacts/intake/ へ保存する
- LogAnalyzerAgent は .artifacts/intake/ のログ系添付を通常の workspace ログより優先して解析候補にする
- KnowledgeRetrieverAgent は hydration 済み ticket 要約と添付パスを優先して使い、不足時のみ再取得する

IntakeAgent と KnowledgeRetrieverAgent は同じ external_ticket / internal_ticket binding を共有してよいが、責務は分ける。

- IntakeAgent: 明示 ticket ID がある場合の初期 hydration と workspace への投影
- KnowledgeRetrieverAgent: 取得済み情報を使った照合と、必要時のみの再取得

## 7. 優先順位

logical tool の解決は次のルールに従う。

1. `tools.logical_tools.<logical_tool>` が定義されていればそれを使う
2. 未定義の logical tool は各 role の既定実装を使う
3. `enabled: true` かつ `provider: mcp` の logical tool に server / tool / mcp_manifest_path が欠けていれば起動時にエラーとする

## 8. LibreOffice 設定

Office 系ファイルの PDF 変換では `tools.libreoffice_command` を使う。

- 指定値は `soffice` のような実行名でも、絶対パスでもよい
- 未指定時は `soffice`、`libreoffice` の順で探索する

例:

```yaml
support_ope_agents:
  tools:
    libreoffice_command: /usr/bin/soffice
```

## 9. document_sources 未設定時

`agents.KnowledgeRetrieverAgent.document_sources` が空の場合、既定の `search_documents` 実装は「参照可能なドキュメントがないので回答できません。」という旨のメッセージを返す。
この状態では KnowledgeRetrieverAgent は document source を根拠にした回答を返さず、ticket source が設定されていればそちらの結果のみを補助情報として扱う。

`agents.ComplianceReviewerAgent.document_sources` が空の場合、既定の `check_policy` 実装はポリシー照合結果を返せず、修正要否へ「確認根拠となるポリシー文書を取得できませんでした」を含める。

`agents.ComplianceReviewerAgent.max_review_loops` を超えてもレビューが通らない場合、SuperVisorAgent は差戻し論点を state に残したまま人手確認へ渡す。

## 10. source 単位の結果

KnowledgeRetrieverAgent は source ごとに次のような結果を返す方針とする。

- source_name
- source_description
- summary: 生成要約ではなく raw snippet
- matched_paths
- evidence

feature list 系の問い合わせでは、`feature_bullets` も返し、DraftWriterAgent がそのまま箇条書き回答へ変換できるようにする。

Supervisor はこの結果から採用 source を選び、shared/context.md に採用した source 名を残す。
また、最終採用した 1 件は CaseState の `knowledge_retrieval_final_adopted_source` に保持する。working memory には source ごとの raw result も追記する。

ComplianceReviewerAgent も同様に source 単位の結果を返し、`compliance_review_adopted_sources` に採用 source を保持する。

## 11. instruction override と tool docs 下書き

- Supervisor の Intake 出力評価観点は [src/support_ope_agents/instructions/defaults/SuperVisorAgent.md](/home/user/source/repos/support-ope-agents/src/support_ope_agents/instructions/defaults/SuperVisorAgent.md) に既定値を置く
- `config_paths.instructions_path` を設定すると、同名の SuperVisorAgent.md でこの評価観点を丸ごと上書きできる
- docs/tools の下書きは `support-ope-agents export-tool-docs --config config.yml --output-dir docs/tools/generated` で生成できる