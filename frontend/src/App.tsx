import { startTransition, useEffect, useState } from 'react';
import {
  browseWorkspace,
  createCase,
  downloadWorkspaceUrl,
  getSavedAuthToken,
  listCases,
  loadFile,
  loadHistory,
  loadRawFileBlob,
  loadUiConfig,
  rawFileUrl,
  resumeCustomerInput,
  saveAuthToken,
  sendAction,
  uploadWorkspaceFile,
} from './api';
import type {
  CaseSummary,
  ChatMessage,
  RuntimeEnvelope,
  WorkspaceBrowseResponse,
  WorkspaceEntry,
  WorkspaceFileResponse,
  UiConfigResponse,
} from './types';

type PendingQuestion = {
  traceId: string;
  answerKey?: string;
  questionText: string;
};

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return '時刻未記録';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('ja-JP', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function describeRun(result: RuntimeEnvelope): string {
  if (result.requires_customer_input) {
    return '追加の顧客情報が必要です';
  }
  if (result.requires_approval) {
    return '承認待ちの状態です';
  }
  return result.workflow_label || result.plan_summary || '処理が完了しました';
}

export default function App() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceBrowseResponse | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<WorkspaceEntry | null>(null);
  const [preview, setPreview] = useState<WorkspaceFileResponse | null>(null);
  const [draftPrompt, setDraftPrompt] = useState('');
  const [queuedFiles, setQueuedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [statusLine, setStatusLine] = useState('ケースを選択するか、そのまま最初のメッセージを送信してください。');
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
  const [authToken, setAuthToken] = useState(() => getSavedAuthToken());
  const [inlinePreviewUrl, setInlinePreviewUrl] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false);
  const [uiConfig, setUiConfig] = useState<UiConfigResponse>({
    app_name: 'Support Desk',
    target_label: null,
    target_description: null,
    auth_required: false,
  });

  useEffect(() => {
    void refreshUiConfig();
    void refreshCases();
  }, []);

  useEffect(() => {
    return () => {
      if (inlinePreviewUrl) {
        URL.revokeObjectURL(inlinePreviewUrl);
      }
    };
  }, [inlinePreviewUrl]);

  async function refreshCases() {
    const nextCases = await listCases();
    startTransition(() => {
      setCases(nextCases);
    });
    if (!selectedCase && nextCases.length > 0) {
      await selectCase(nextCases[0]);
    }
  }

  async function refreshUiConfig() {
    try {
      const config = await loadUiConfig();
      setUiConfig(config);
      if (config.auth_required && !getSavedAuthToken()) {
        setStatusLine('この画面は認証トークンが必要です。右上に入力してください。');
      }
    } catch {
      setStatusLine('UI 設定の取得に失敗しました。');
    }
  }

  async function selectCase(target: CaseSummary) {
    setSelectedCase(target);
    setStatusLine(`${target.case_id} を読み込み中です。`);
    const [history, workspace] = await Promise.all([
      loadHistory(target.case_id, target.workspace_path),
      browseWorkspace(target.case_id, target.workspace_path),
    ]);
    startTransition(() => {
      setMessages(history.messages);
      setWorkspaceView(workspace);
      setSelectedEntry(null);
      setPreview(null);
      setPendingQuestion(null);
    });
    setStatusLine(`${target.case_id} を表示しています。`);
  }

  async function openDirectory(path: string) {
    if (!selectedCase) {
      return;
    }
    const workspace = await browseWorkspace(selectedCase.case_id, selectedCase.workspace_path, path);
    setWorkspaceView(workspace);
    setPreview(null);
    setSelectedEntry(null);
    if (inlinePreviewUrl) {
      URL.revokeObjectURL(inlinePreviewUrl);
      setInlinePreviewUrl(null);
    }
  }

  async function openEntry(entry: WorkspaceEntry) {
    if (!selectedCase) {
      return;
    }
    setSelectedEntry(entry);
    if (entry.kind === 'directory') {
      await openDirectory(entry.path);
      return;
    }
    const nextPreview = await loadFile(selectedCase.case_id, selectedCase.workspace_path, entry.path);
    if (inlinePreviewUrl) {
      URL.revokeObjectURL(inlinePreviewUrl);
      setInlinePreviewUrl(null);
    }
    if ((nextPreview.mime_type || '').startsWith('image/') || nextPreview.mime_type === 'application/pdf') {
      const blob = await loadRawFileBlob(selectedCase.case_id, selectedCase.workspace_path, entry.path);
      setInlinePreviewUrl(URL.createObjectURL(blob));
    }
    setPreview(nextPreview);
  }

  function persistAuthToken() {
    saveAuthToken(authToken);
    setStatusLine(authToken.trim() ? '認証トークンを保存しました。' : '認証トークンをクリアしました。');
  }

  async function submitMessage() {
    if (busy) {
      return;
    }
    const trimmedPrompt = draftPrompt.trim();
    if (!trimmedPrompt && queuedFiles.length === 0) {
      return;
    }

    setBusy(true);
    setStatusLine('送信中です。');

    try {
      let activeCase = selectedCase;
      if (!activeCase) {
        const created = await createCase(trimmedPrompt || '新規ケース');
        activeCase = {
          case_id: created.case_id,
          case_title: created.case_title,
          workspace_path: created.case_path,
          updated_at: new Date().toISOString(),
          message_count: 0,
        };
        setSelectedCase(activeCase);
      }

      for (const file of queuedFiles) {
        await uploadWorkspaceFile(activeCase.case_id, activeCase.workspace_path, '.evidence', file);
      }

      let result: RuntimeEnvelope;
      if (pendingQuestion && trimmedPrompt) {
        result = await resumeCustomerInput(
          activeCase.case_id,
          pendingQuestion.traceId,
          activeCase.workspace_path,
          trimmedPrompt,
          pendingQuestion.answerKey
        );
      } else {
        result = await sendAction(trimmedPrompt || '添付ファイルを確認してください。', activeCase.workspace_path, activeCase.case_id);
      }

      const [history, workspace, nextCases] = await Promise.all([
        loadHistory(activeCase.case_id, activeCase.workspace_path),
        browseWorkspace(activeCase.case_id, activeCase.workspace_path, workspaceView?.current_path || '.'),
        listCases(),
      ]);

      startTransition(() => {
        setMessages(history.messages);
        setWorkspaceView(workspace);
        setCases(nextCases);
      });

      const questions = (result.state.intake_followup_questions as Record<string, string> | undefined) ?? {};
      const firstQuestionKey = Object.keys(questions)[0];
      if (result.requires_customer_input && firstQuestionKey) {
        setPendingQuestion({
          traceId: result.trace_id || '',
          answerKey: firstQuestionKey,
          questionText: questions[firstQuestionKey],
        });
      } else {
        setPendingQuestion(null);
      }

      setDraftPrompt('');
      setQueuedFiles([]);
      setStatusLine(describeRun(result));
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : '送信中にエラーが発生しました。');
    } finally {
      setBusy(false);
    }
  }

  const currentPath = workspaceView?.current_path || '.';
  const breadcrumbs = currentPath === '.' ? ['.'] : currentPath.split('/');
  const parentPath = currentPath === '.' ? null : currentPath.includes('/') ? currentPath.slice(0, currentPath.lastIndexOf('/')) : '.';
  const shellClassName = [
    'shell',
    sidebarCollapsed ? 'shell-sidebar-collapsed' : '',
    workspaceCollapsed ? 'shell-workspace-collapsed' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={shellClassName}>
      <aside className="sidebar panel">
        <div className="panel-header sidebar-header">
          <div className="panel-title-block">
            <div className="panel-label-row">
              <button
                className="ghost-button panel-toggle icon-only panel-toggle-compact"
                type="button"
                onClick={() => setSidebarCollapsed((current) => !current)}
                aria-expanded={!sidebarCollapsed}
                aria-controls="session-index-content"
                aria-label={sidebarCollapsed ? 'Session Index を展開' : 'Session Index を折りたたむ'}
              >
                <span className="hamburger-icon" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
              </button>
              <p className="eyebrow">Session Index</p>
            </div>
            <h1>{uiConfig.app_name}</h1>
          </div>
        </div>
        <div id="session-index-content" className={`panel-content ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
          {uiConfig.target_label ? (
            <div className="target-chip-block panel-subtle">
              <span className="target-chip">{uiConfig.target_label}</span>
              {uiConfig.target_description ? <p>{uiConfig.target_description}</p> : null}
            </div>
          ) : null}
          <div className="sidebar-actions">
            <button className="ghost-button" onClick={() => setSelectedCase(null)} type="button">
              新規ケース
            </button>
          </div>
          <p className="panel-copy">ケースごとの会話履歴を左側で切り替えます。</p>
          <div className="case-list">
            {cases.map((item) => (
              <button
                key={item.case_id}
                type="button"
                className={`case-card ${selectedCase?.case_id === item.case_id ? 'active' : ''}`}
                onClick={() => void selectCase(item)}
              >
                <span className="case-title">{item.case_title || item.case_id}</span>
                <span className="case-id">{item.case_id}</span>
                <span className="case-meta">{item.message_count} messages</span>
                <span className="case-meta">{formatTimestamp(item.updated_at)}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="chat-stage panel">
        <div className="panel-header with-border">
          <div>
            <p className="eyebrow">Active Conversation</p>
            <h2>{selectedCase?.case_title || selectedCase?.case_id || '新しい会話を開始'}</h2>
            {selectedCase?.case_title ? <div className="conversation-case-id">{selectedCase.case_id}</div> : null}
          </div>
          <div className="status-stack">
            <label className="auth-box">
              <span>Auth Token</span>
              <input
                type="password"
                value={authToken}
                onChange={(event) => setAuthToken(event.target.value)}
                placeholder={uiConfig.auth_required ? 'この画面では必須です' : '未設定なら空欄のまま'}
              />
              <button className="ghost-button" type="button" onClick={persistAuthToken}>
                保存
              </button>
            </label>
            <div className="status-pill">{statusLine}</div>
          </div>
        </div>

        <div className="messages">
          {messages.length === 0 ? (
            <div className="empty-state">
              <h3>AIチャットの開始準備ができています。</h3>
              <p>問い合わせ内容を書き、必要ならファイルを添付して送信してください。</p>
            </div>
          ) : (
            messages.map((message, index) => (
              <article key={`${message.trace_id || 'local'}-${index}`} className={`message ${message.role}`}>
                <div className="message-role">{message.role === 'assistant' ? 'Agent' : 'You'}</div>
                <p>{message.content}</p>
                <span className="message-meta">{formatTimestamp(message.created_at)} {message.event ? `· ${message.event}` : ''}</span>
              </article>
            ))
          )}
        </div>

        {pendingQuestion ? (
          <div className="followup-banner">
            <strong>追加確認</strong>
            <span>{pendingQuestion.questionText}</span>
          </div>
        ) : null}

        <div className="composer panel-subtle">
          <textarea
            value={draftPrompt}
            onChange={(event) => setDraftPrompt(event.target.value)}
            placeholder={pendingQuestion ? '追加情報を入力してください' : '問い合わせ内容を入力してください'}
            rows={4}
          />
          <div className="composer-row">
            <label className="upload-chip" htmlFor="file-upload">
              ファイルを追加
            </label>
            <input
              id="file-upload"
              type="file"
              multiple
              onChange={(event) => setQueuedFiles(Array.from(event.target.files || []))}
            />
            <div className="queued-files">
              {queuedFiles.map((file) => (
                <span key={file.name}>{file.name}</span>
              ))}
            </div>
            <button className="send-button" type="button" onClick={() => void submitMessage()} disabled={busy}>
              {busy ? '送信中...' : '送信'}
            </button>
          </div>
        </div>
      </main>

      <section className="workspace panel">
        <div className="panel-header with-border">
          <div className="panel-title-block">
            <div className="panel-label-row">
              <button
                className="ghost-button panel-toggle icon-only panel-toggle-compact"
                type="button"
                onClick={() => setWorkspaceCollapsed((current) => !current)}
                aria-expanded={!workspaceCollapsed}
                aria-controls="workspace-content"
                aria-label={workspaceCollapsed ? 'Workspace を展開' : 'Workspace を折りたたむ'}
              >
                <span className="hamburger-icon" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
              </button>
              <p className="eyebrow">Workspace</p>
            </div>
            <h2>{selectedCase ? 'ファイルツリー' : 'ケース未選択'}</h2>
          </div>
          <div className="panel-actions">
            {selectedCase ? (
              <a className="ghost-button panel-action-secondary" href={downloadWorkspaceUrl(selectedCase.case_id, selectedCase.workspace_path)}>
                ZIPを取得
              </a>
            ) : null}
          </div>
        </div>

        <div id="workspace-content" className={`panel-content ${workspaceCollapsed ? 'is-collapsed' : ''}`}>
          <div className="breadcrumbs">
            <button type="button" onClick={() => void openDirectory('.')} disabled={!selectedCase}>
              root
            </button>
            {breadcrumbs.map((crumb, index) => (
              <span key={`${crumb}-${index}`}>{crumb}</span>
            ))}
          </div>

          <div className="workspace-grid">
            <div className="tree-view">
              {parentPath !== null ? (
                <button
                  key="__parent__"
                  type="button"
                  className="tree-node tree-node-parent"
                  onClick={() => void openDirectory(parentPath)}
                >
                  <span className="tree-entry-icon parent" aria-hidden="true" />
                  <div className="tree-entry-copy">
                    <strong>..</strong>
                    <span className="tree-entry-kind">親ディレクトリ</span>
                  </div>
                </button>
              ) : null}
              {(workspaceView?.entries || []).map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  className={`tree-node ${selectedEntry?.path === entry.path ? 'active' : ''}`}
                  onClick={() => void openEntry(entry)}
                >
                  <span className={`tree-entry-icon ${entry.kind === 'directory' ? 'directory' : 'file'}`} aria-hidden="true" />
                  <div className="tree-entry-copy">
                    <strong>{entry.name}</strong>
                    <span className="tree-entry-kind">{entry.kind === 'directory' ? 'フォルダ' : 'ファイル'}</span>
                  </div>
                </button>
              ))}
            </div>

            <div className="preview-pane panel-subtle">
              {preview ? (
                <>
                  <div className="preview-header">
                    <div>
                      <strong>{preview.name}</strong>
                      <span>{preview.mime_type || 'unknown'}</span>
                    </div>
                    <a
                      className="ghost-button"
                      href={selectedCase ? rawFileUrl(selectedCase.case_id, selectedCase.workspace_path, preview.path) : '#'}
                      target="_blank"
                      rel="noreferrer"
                    >
                      別ウィンドウで表示
                    </a>
                  </div>
                  {preview.preview_available ? (
                    <pre>{preview.content}</pre>
                  ) : inlinePreviewUrl && (preview.mime_type || '').startsWith('image/') ? (
                    <div className="binary-preview-frame">
                      <img src={inlinePreviewUrl} alt={preview.name} className="binary-image-preview" />
                    </div>
                  ) : inlinePreviewUrl && preview.mime_type === 'application/pdf' ? (
                    <iframe title={preview.name} src={inlinePreviewUrl} className="binary-pdf-preview" />
                  ) : (
                    <div className="empty-state compact">
                      <h3>このファイル形式はプレビュー対象外です。</h3>
                      <p>別ウィンドウ表示で開いて確認してください。</p>
                    </div>
                  )}
                </>
              ) : (
                <div className="empty-state empty-preview compact">
                  <h3>プレビュー</h3>
                  <p>右側のツリーからファイルを選択すると内容を表示します。</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}