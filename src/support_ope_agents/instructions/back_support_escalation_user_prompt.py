# バックサポートエスカレーション用ユーザープロンプト

USER_PROMPT_TEMPLATE = """
目的:
- バックサポートへ渡す問い合わせ文案を日本語で作成する
- 連携すべきログ、再現情報、添付候補ファイルを整理する
- shared と agents の両方を確認し、根拠に使った path を evidence_paths に入れる
- required_log_files には不足しているが収集依頼すべきログや再現情報を入れる
- attachment_candidates には既に memory 配下に存在し、問い合わせに添付すべき path を入れる
- inquiry_draft は、そのままバックサポートに渡せる文面にする
- evidence_paths には実際に読んだ backend path を必ず 2 件以上入れる
依頼内容:
{query}
"""
