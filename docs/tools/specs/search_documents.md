# search_documents

## 1. 目的

構成済み document_sources を横断検索し、関連ナレッジや根拠候補を収集する。

## 2. 利用エージェント

- InvestigateAgent

## 3. 既定実装 / 接続点

- 論理ツール名: search_documents
- 既定実装: [src/support_ope_agents/tools/default_search_documents.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_search_documents.py)
- 参照定義は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.InvestigateAgent.document_sources に置く

## 4. 実装状況

- 区分: implemented
- 実装済み

## 5. 既定 builtin の挙動

- DeepAgents backend の `/knowledge/<source_name>/` を search_documents builtin から DeepAgent へ渡し、検索判断自体は DeepAgents に委ねる
- `extraction_mode: relaxed` では関連語も含めた広めの探索を依頼する
- `extraction_mode: raw_backend` では DeepAgents が選んだ主要文書の生テキストも payload に残す
- source ごとに `source_name`、`summary`、`matched_paths`、`evidence`、`feature_bullets` を JSON で返す
- `summary` には生成要約ではなく、該当 Markdown から抽出した raw snippet または重要抜粋を入れる
- feature list 系の問い合わせでは `feature_bullets` を優先的に返す