import { startTransition, useEffect, useId, useRef, useState } from 'react';
import mermaid from 'mermaid';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  browseWorkspace,
  createCase,
  downloadWorkspaceUrl,
  generateReport,
  getSavedAuthToken,
  listCases,
  loadControlCatalog,
  loadFile,
  loadHistory,
  loadRawFileBlob,
  loadRuntimeAudit,
  loadUiConfig,
  renderedPreviewUrl,
  rawFileUrl,
  resumeCustomerInput,
  saveAuthToken,
  sendAction,
  uploadWorkspaceFile,
} from './api';
import type {
  CaseSummary,
  ChatMessage,
  ControlCatalogResponse,
  RuntimeEnvelope,
  RuntimeAuditResponse,
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

type SubmissionStage = 'creating-case' | 'uploading-files' | 'running-workflow' | 'syncing-results';

const submissionStageCopy: Record<SubmissionStage, { title: string; detail: string }> = {
  'creating-case': {
    title: 'ケースを作成しています',
    detail: '会話履歴と作業領域の準備を進めています。',
  },
  'uploading-files': {
    title: '添付ファイルをアップロードしています',
    detail: '調査に必要な証跡をワークスペースへ取り込んでいます。',
  },
  'running-workflow': {
    title: '回答を準備しています',
    detail: 'ログやナレッジ、添付ファイルを確認しています。',
  },
  'syncing-results': {
    title: '結果を反映しています',
    detail: '会話履歴とワークスペースの最新状態を読み込んでいます。',
  },
};

let mermaidInitialized = false;

function ensureMermaidInitialized() {
  if (mermaidInitialized) {
    return;
  }

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'neutral',
  });
  mermaidInitialized = true;
}

function MermaidBlock({ chart }: { chart: string }) {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState<string | null>(null);
  const blockId = useId().replace(/:/g, '-');

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      try {
        ensureMermaidInitialized();
        const { svg: nextSvg } = await mermaid.render(`mermaid-${blockId}`, chart);
        if (!cancelled) {
          setSvg(nextSvg);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setSvg('');
          setError('Mermaid の描画に失敗しました。');
        }
      }
    }

    void renderChart();

    return () => {
      cancelled = true;
    };
  }, [blockId, chart]);

  if (error) {
    return (
      <div className="mermaid-fallback">
        <p>{error}</p>
        <pre>{chart}</pre>
      </div>
    );
  }

  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}

type MarkdownContentProps = {
  content: string;
  basePath?: string;
  onWorkspaceLinkClick?: (path: string) => void | Promise<void>;
};

function normalizeWorkspacePath(path: string): string | null {
  const segments = path.split('/');
  const normalized: string[] = [];

  for (const segment of segments) {
    if (!segment || segment === '.') {
      continue;
    }
    if (segment === '..') {
      if (normalized.length === 0) {
        return null;
      }
      normalized.pop();
      continue;
    }
    normalized.push(segment);
  }

  return normalized.join('/') || '.';
}

function dirname(path: string): string {
  if (!path || path === '.') {
    return '.';
  }
  const lastSlash = path.lastIndexOf('/');
  return lastSlash >= 0 ? path.slice(0, lastSlash) || '.' : '.';
}

function resolveWorkspaceLink(href: string, basePath?: string): string | null {
  const trimmedHref = href.trim();
  if (!trimmedHref || trimmedHref.startsWith('#')) {
    return null;
  }
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(trimmedHref) || trimmedHref.startsWith('mailto:') || trimmedHref.startsWith('tel:')) {
    return null;
  }
  if (trimmedHref.startsWith('/knowledge/')) {
    return null;
  }

  const pathOnly = trimmedHref.split('#', 1)[0].split('?', 1)[0];
  if (!pathOnly) {
    return null;
  }

  const candidate = pathOnly.startsWith('/')
    ? pathOnly.slice(1)
    : `${dirname(basePath || '.').replace(/\/$/, '')}/${pathOnly}`;
  return normalizeWorkspacePath(candidate);
}

function MarkdownContent({ content, basePath, onWorkspaceLinkClick }: MarkdownContentProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a({ href, children, ...props }) {
          const resolvedPath = href ? resolveWorkspaceLink(href, basePath) : null;
          if (resolvedPath && onWorkspaceLinkClick) {
            return (
              <a
                href={href}
                {...props}
                onClick={(event) => {
                  event.preventDefault();
                  void onWorkspaceLinkClick(resolvedPath);
                }}
              >
                {children}
              </a>
            );
          }

          return (
            <a href={href} {...props}>
              {children}
            </a>
          );
        },
        code({ className, children, ...props }) {
          const language = /language-([\w-]+)/.exec(className || '')?.[1]?.toLowerCase();
          if (language === 'mermaid') {
            return <MermaidBlock chart={String(children).replace(/\n$/, '')} />;
          }

          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

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

function isMarkdownFile(name: string, mimeType?: string | null): boolean {
  const normalizedName = name.toLowerCase();
  const normalizedMime = (mimeType || '').toLowerCase();
  return (
    normalizedName.endsWith('.md') ||
    normalizedName.endsWith('.markdown') ||
    normalizedMime === 'text/markdown' ||
    normalizedMime === 'text/x-markdown'
  );
}

function isReportMarkdown(entry: WorkspaceEntry): boolean {
  return entry.kind === 'file' && isMarkdownFile(entry.name);
}

const REPORT_SUBDIR = '.report';

function findLatestTraceId(messages: ChatMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const traceId = messages[index]?.trace_id?.trim();
    if (traceId) {
      return traceId;
    }
  }
  return '';
}

function sortCasesByUpdatedAt(cases: CaseSummary[]): CaseSummary[] {
  return [...cases].sort((left, right) => {
    const leftTime = new Date(left.updated_at || 0).getTime();
    const rightTime = new Date(right.updated_at || 0).getTime();
    return rightTime - leftTime;
  });
}

type StandalonePreviewParams = {
  caseId: string;
  workspacePath: string;
  path: string;
};

function getStandalonePreviewParams(): StandalonePreviewParams | null {
  const params = new URLSearchParams(window.location.search);
  if (params.get('preview') !== '1') {
    return null;
  }

  const caseId = params.get('case_id')?.trim() || '';
  const workspacePath = params.get('workspace_path')?.trim() || '';
  const path = params.get('path')?.trim() || '';
  if (!caseId || !workspacePath || !path) {
    return null;
  }

  return { caseId, workspacePath, path };
}

function StandalonePreview({ caseId, workspacePath, path }: StandalonePreviewParams) {
  const [preview, setPreview] = useState<WorkspaceFileResponse | null>(null);
  const [inlinePreviewUrl, setInlinePreviewUrl] = useState<string | null>(null);
  const [status, setStatus] = useState('プレビューを読み込み中です。');

  async function openLinkedPreview(targetPath: string) {
    window.location.href = renderedPreviewUrl(caseId, workspacePath, targetPath);
  }

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const nextPreview = await loadFile(caseId, workspacePath, path);
        if (cancelled) {
          return;
        }
        if ((nextPreview.mime_type || '').startsWith('image/') || nextPreview.mime_type === 'application/pdf') {
          const blob = await loadRawFileBlob(caseId, workspacePath, path);
          if (cancelled) {
            return;
          }
          setInlinePreviewUrl(URL.createObjectURL(blob));
        }

        setPreview(nextPreview);
        setStatus(nextPreview.name);
      } catch {
        if (!cancelled) {
          setStatus('プレビューの取得に失敗しました。');
        }
      }
    }

    void run();

    return () => {
      cancelled = true;
      if (inlinePreviewUrl) {
        URL.revokeObjectURL(inlinePreviewUrl);
      }
    };
  }, [caseId, workspacePath, path]);

  return (
    <div className="standalone-preview-page">
      <div className="standalone-preview-card panel">
        <div className="preview-header standalone-preview-header">
          <div>
            <p className="eyebrow">Rendered Preview</p>
            <strong>{preview?.name || path}</strong>
            <span>{preview?.mime_type || status}</span>
          </div>
          <a
            className="ghost-button"
            href={rawFileUrl(caseId, workspacePath, path)}
            target="_blank"
            rel="noreferrer"
          >
            raw を開く
          </a>
        </div>
        {preview ? (
          preview.preview_available ? (
            isMarkdownFile(preview.name, preview.mime_type) ? (
              <div className="preview-markdown standalone-preview-content markdown-body">
                <MarkdownContent content={preview.content || ''} basePath={preview.path} onWorkspaceLinkClick={openLinkedPreview} />
              </div>
            ) : (
              <pre className="standalone-preview-content">{preview.content}</pre>
            )
          ) : inlinePreviewUrl && (preview.mime_type || '').startsWith('image/') ? (
            <div className="binary-preview-frame standalone-preview-content">
              <img src={inlinePreviewUrl} alt={preview.name} className="binary-image-preview" />
            </div>
          ) : inlinePreviewUrl && preview.mime_type === 'application/pdf' ? (
            <iframe title={preview.name} src={inlinePreviewUrl} className="binary-pdf-preview standalone-preview-content" />
          ) : (
            <div className="empty-state compact standalone-preview-content">
              <h3>このファイル形式はレンダリング対象外です。</h3>
              <p>必要に応じて raw を開いて確認してください。</p>
            </div>
          )
        ) : (
          <div className="empty-state compact standalone-preview-content">
            <h3>プレビューを準備中です。</h3>
            <p>{status}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const standalonePreview = getStandalonePreviewParams();
  if (standalonePreview) {
    return <StandalonePreview {...standalonePreview} />;
  }

  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCase, setSelectedCase] = useState<CaseSummary | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceBrowseResponse | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<WorkspaceEntry | null>(null);
  const [preview, setPreview] = useState<WorkspaceFileResponse | null>(null);
  const [draftPrompt, setDraftPrompt] = useState('');
  const [queuedFiles, setQueuedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [isAwaitingResponse, setIsAwaitingResponse] = useState(false);
  const [submissionStage, setSubmissionStage] = useState<SubmissionStage>('running-workflow');
  const [statusLine, setStatusLine] = useState('ケースを選択するか、そのまま最初のメッセージを送信してください。');
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
  const [authToken, setAuthToken] = useState(() => getSavedAuthToken());
  const [inlinePreviewUrl, setInlinePreviewUrl] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false);
  const [controlCatalog, setControlCatalog] = useState<ControlCatalogResponse | null>(null);
  const [runtimeAudit, setRuntimeAudit] = useState<RuntimeAuditResponse | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const [uiConfig, setUiConfig] = useState<UiConfigResponse>({
    app_name: 'Support Desk',
    target_label: null,
    target_description: null,
    auth_required: false,
  });

  useEffect(() => {
    void refreshUiConfig();
    void refreshCases();
    void refreshControlCatalog();
  }, []);

  useEffect(() => {
    return () => {
      if (inlinePreviewUrl) {
        URL.revokeObjectURL(inlinePreviewUrl);
      }
    };
  }, [inlinePreviewUrl]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, isAwaitingResponse, submissionStage, pendingQuestion]);

  async function refreshCases() {
    const nextCases = sortCasesByUpdatedAt(await listCases());
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

  async function refreshControlCatalog() {
    try {
      setControlCatalog(await loadControlCatalog());
    } catch {
      setControlCatalog(null);
    }
  }

  async function refreshRuntimeAudit(target: CaseSummary, traceId: string | null | undefined) {
    const normalizedTraceId = traceId?.trim();
    if (!normalizedTraceId) {
      setRuntimeAudit(null);
      return;
    }
    try {
      setRuntimeAudit(await loadRuntimeAudit(target.case_id, target.workspace_path, normalizedTraceId));
    } catch {
      setRuntimeAudit(null);
    }
  }

  async function copyRawText(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setStatusLine('raw_text をコピーしました。');
    } catch {
      setStatusLine('raw_text のコピーに失敗しました。');
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
    await refreshRuntimeAudit(target, findLatestTraceId(history.messages));
    setStatusLine(`${target.case_id} を表示しています。`);
  }

  function startNewCase() {
    setSelectedCase(null);
    startTransition(() => {
      setMessages([]);
      setWorkspaceView(null);
      setSelectedEntry(null);
      setPreview(null);
      setPendingQuestion(null);
      setDraftPrompt('');
      setQueuedFiles([]);
      setRuntimeAudit(null);
    });
    if (inlinePreviewUrl) {
      URL.revokeObjectURL(inlinePreviewUrl);
      setInlinePreviewUrl(null);
    }
    setStatusLine('新しい会話を開始できます。問い合わせ内容を入力してください。');
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

  async function openWorkspaceFileFromLink(path: string) {
    if (!selectedCase) {
      return;
    }

    try {
      const nextPreview = await loadFile(selectedCase.case_id, selectedCase.workspace_path, path);
      const containerPath = dirname(path);
      const nextWorkspace = await browseWorkspace(selectedCase.case_id, selectedCase.workspace_path, containerPath);

      if (inlinePreviewUrl) {
        URL.revokeObjectURL(inlinePreviewUrl);
        setInlinePreviewUrl(null);
      }
      if ((nextPreview.mime_type || '').startsWith('image/') || nextPreview.mime_type === 'application/pdf') {
        const blob = await loadRawFileBlob(selectedCase.case_id, selectedCase.workspace_path, path);
        setInlinePreviewUrl(URL.createObjectURL(blob));
      }

      startTransition(() => {
        setWorkspaceView(nextWorkspace);
        setSelectedEntry(nextWorkspace.entries.find((entry) => entry.path === path) ?? { name: nextPreview.name, path, kind: 'file' });
        setPreview(nextPreview);
      });
      setStatusLine(`${nextPreview.name} をプレビューしています。`);
    } catch {
      setStatusLine(`ワークスペース内のリンク先 ${path} を開けませんでした。`);
    }
  }

  async function openLatestReport() {
    if (!selectedCase) {
      return;
    }

    setStatusLine('最新レポートを確認しています。');

    try {
      const reportWorkspace = await browseWorkspace(selectedCase.case_id, selectedCase.workspace_path, REPORT_SUBDIR);
      const latestReport = reportWorkspace.entries
        .filter(isReportMarkdown)
        .sort((left, right) => {
          const leftTime = new Date(left.updated_at || 0).getTime();
          const rightTime = new Date(right.updated_at || 0).getTime();
          return rightTime - leftTime;
        })[0];

      if (!latestReport) {
        setStatusLine(`${REPORT_SUBDIR} フォルダに表示可能な Markdown レポートが見つかりません。`);
        return;
      }

      window.open(
        renderedPreviewUrl(selectedCase.case_id, selectedCase.workspace_path, latestReport.path),
        '_blank',
        'noopener,noreferrer'
      );
      setStatusLine(`${latestReport.name} を別ウィンドウで開きました。`);
    } catch {
      setStatusLine('最新レポートの取得に失敗しました。');
    }
  }

  async function createLatestReport() {
    if (!selectedCase) {
      return;
    }

    const traceId = findLatestTraceId(messages);
    if (!traceId) {
      setStatusLine('レポート生成対象の trace_id が見つかりません。先に会話を実行してください。');
      return;
    }

    setBusy(true);
    setStatusLine('レポートを生成しています。');

    try {
      const result = await generateReport(selectedCase.case_id, selectedCase.workspace_path, traceId);
      const [workspace, nextCases] = await Promise.all([
        browseWorkspace(selectedCase.case_id, selectedCase.workspace_path, workspaceView?.current_path || '.'),
        listCases(),
      ]);
      await refreshRuntimeAudit(selectedCase, traceId);

      startTransition(() => {
        setWorkspaceView(workspace);
        setCases(sortCasesByUpdatedAt(nextCases));
      });
      setStatusLine(`${result.report_path.split('/').pop() || 'レポート'} を生成しました。`);
    } catch (error) {
      setStatusLine(error instanceof Error ? error.message : 'レポート生成に失敗しました。');
    } finally {
      setBusy(false);
    }
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
    setIsAwaitingResponse(true);
    setSubmissionStage(selectedCase ? 'running-workflow' : 'creating-case');
    setStatusLine('回答を生成しています。');

    try {
      let activeCase = selectedCase;
      if (!activeCase) {
        setSubmissionStage('creating-case');
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

      if (queuedFiles.length > 0) {
        setSubmissionStage('uploading-files');
      }
      for (const file of queuedFiles) {
        await uploadWorkspaceFile(activeCase.case_id, activeCase.workspace_path, '.evidence', file);
      }

      setSubmissionStage('running-workflow');
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

      setSubmissionStage('syncing-results');
      const [history, workspace, nextCases] = await Promise.all([
        loadHistory(activeCase.case_id, activeCase.workspace_path),
        browseWorkspace(activeCase.case_id, activeCase.workspace_path, workspaceView?.current_path || '.'),
        listCases(),
      ]);
      await refreshRuntimeAudit(activeCase, result.trace_id || findLatestTraceId(history.messages));

      startTransition(() => {
        setMessages(history.messages);
        setWorkspaceView(workspace);
        setCases(sortCasesByUpdatedAt(nextCases));
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
      setIsAwaitingResponse(false);
      setSubmissionStage('running-workflow');
      setBusy(false);
    }
  }

  const currentPath = workspaceView?.current_path || '.';
  const breadcrumbs = currentPath === '.' ? ['.'] : currentPath.split('/');
  const parentPath = currentPath === '.' ? null : currentPath.includes('/') ? currentPath.slice(0, currentPath.lastIndexOf('/')) : '.';
  const isAuthenticated = Boolean(authToken.trim());
  const userLabel = uiConfig.auth_required ? (isAuthenticated ? '認証済み' : '未認証') : 'ゲスト';
  const userMeta = uiConfig.auth_required ? (isAuthenticated ? 'サインイン済み' : 'サインインが必要です') : '認証不要';
  const submissionCopy = submissionStageCopy[submissionStage];
  const shellClassName = [
    'shell',
    sidebarCollapsed ? 'shell-sidebar-collapsed' : '',
    workspaceCollapsed ? 'shell-workspace-collapsed' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className="app-frame">
      <header className="topbar panel-subtle">
        <div className="topbar-brand">
          <strong>{uiConfig.app_name}</strong>
        </div>
        <div className="topbar-actions">
          <div className="status-pill topbar-status">{statusLine}</div>
          {uiConfig.auth_required ? (
            <label className="auth-box topbar-auth-box">
              <span>Auth Token</span>
              <input
                type="password"
                value={authToken}
                onChange={(event) => setAuthToken(event.target.value)}
                placeholder="この画面では必須です"
              />
              <button className="ghost-button" type="button" onClick={persistAuthToken}>
                保存
              </button>
            </label>
          ) : null}
          <div className="user-chip panel-subtle" aria-label="ユーザー状態">
            <span className={`user-chip-indicator ${isAuthenticated ? 'signed-in' : 'guest'}`} aria-hidden="true" />
            <div className="user-chip-copy">
              <strong>{userLabel}</strong>
              <span>{userMeta}</span>
            </div>
          </div>
        </div>
      </header>

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
            <button className="ghost-button" onClick={startNewCase} type="button">
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
                <div className="message-header">
                  <div className="message-role">{message.role === 'assistant' ? 'Agent' : 'You'}</div>
                  <button
                    className="ghost-button message-copy-button icon-only"
                    type="button"
                    onClick={() => void copyRawText(message.content)}
                    aria-label="raw_text をコピー"
                    title="raw_text をコピー"
                  >
                    <span className="copy-icon" aria-hidden="true" />
                  </button>
                </div>
                <div className="message-body markdown-body">
                  <MarkdownContent content={message.content} onWorkspaceLinkClick={selectedCase ? openWorkspaceFileFromLink : undefined} />
                </div>
                <span className="message-meta">{formatTimestamp(message.created_at)} {message.event ? `· ${message.event}` : ''}</span>
              </article>
            ))
          )}
          {isAwaitingResponse ? (
            <article className="message assistant message-pending" aria-live="polite" aria-busy="true">
              <div className="message-header">
                <div className="message-role">Agent</div>
              </div>
              <div className="message-body">
                <div className="progress-bubble">
                  <span className="progress-spinner" aria-hidden="true" />
                  <div>
                    <strong>{submissionCopy.title}</strong>
                    <p>{submissionCopy.detail}</p>
                  </div>
                </div>
                <div className="progress-steps" aria-hidden="true">
                  <span className={submissionStage === 'creating-case' ? 'is-current' : ''}>ケース作成</span>
                  <span className={submissionStage === 'uploading-files' ? 'is-current' : ''}>添付取込</span>
                  <span className={submissionStage === 'running-workflow' ? 'is-current' : ''}>回答生成</span>
                  <span className={submissionStage === 'syncing-results' ? 'is-current' : ''}>結果反映</span>
                </div>
              </div>
            </article>
          ) : null}
          <div ref={messageEndRef} aria-hidden="true" />
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
            disabled={busy}
          />
          <div className="composer-row">
            <label className={`upload-chip ${busy ? 'is-disabled' : ''}`} htmlFor="file-upload">
              ファイルを追加
            </label>
            <input
              id="file-upload"
              type="file"
              multiple
              disabled={busy}
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
              <>
                <button className="ghost-button panel-action-secondary" type="button" onClick={() => void createLatestReport()} disabled={busy}>
                  レポート生成
                </button>
                <button className="ghost-button panel-action-secondary" type="button" onClick={() => void openLatestReport()}>
                  レポート表示
                </button>
                <a className="ghost-button panel-action-secondary" href={downloadWorkspaceUrl(selectedCase.case_id, selectedCase.workspace_path)}>
                  ZIPを取得
                </a>
              </>
            ) : null}
          </div>
        </div>

        <div id="workspace-content" className={`panel-content ${workspaceCollapsed ? 'is-collapsed' : ''}`}>
          <div className="control-inspector panel-subtle">
            <div className="control-inspector-header">
              <div>
                <p className="eyebrow">Control View</p>
                <strong>制御一覧と実行時監査</strong>
              </div>
              <span className="control-trace-label">{runtimeAudit?.summary.trace_id || 'trace 未選択'}</span>
            </div>
            <div className="control-summary-grid">
              <div className="control-stat-card">
                <span>Control points</span>
                <strong>{controlCatalog?.summary.control_point_count ?? '-'}</strong>
              </div>
              <div className="control-stat-card">
                <span>Workflow nodes</span>
                <strong>{controlCatalog?.summary.workflow_node_count ?? '-'}</strong>
              </div>
              <div className="control-stat-card">
                <span>Logical tools</span>
                <strong>{controlCatalog?.summary.logical_tool_count ?? '-'}</strong>
              </div>
              <div className="control-stat-card">
                <span>Used roles</span>
                <strong>{runtimeAudit?.summary.used_role_count ?? '-'}</strong>
              </div>
            </div>
            {runtimeAudit ? (
              <div className="control-runtime-grid">
                <div className="control-detail-block">
                  <strong>実行結果</strong>
                  <p>Status: {runtimeAudit.summary.status}</p>
                  <p>Workflow: {runtimeAudit.summary.workflow_kind}</p>
                  <p>Result: {runtimeAudit.summary.result}</p>
                  <p>Approval: {runtimeAudit.summary.approval_route}</p>
                </div>
                <div className="control-detail-block">
                  <strong>使用エージェント</strong>
                  <div className="control-chip-list">
                    {runtimeAudit.used_roles.map((role) => (
                      <span key={role} className="control-chip">{role}</span>
                    ))}
                  </div>
                  <p className="control-path">{runtimeAudit.workflow_path.join(' → ')}</p>
                </div>
                <div className="control-detail-block">
                  <strong>発火した制御</strong>
                  <div className="control-decision-list">
                    {runtimeAudit.decision_log.slice(0, 6).map((item) => (
                      <div key={`${item.control_point_id}-${item.outcome}`} className="control-decision-item">
                        <span>{item.category}</span>
                        <strong>{item.control_point_id}</strong>
                        <p>{item.detail}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-state compact control-empty-state">
                <h3>実行時監査はまだありません。</h3>
                <p>ケースを実行すると、直近 trace の分岐と制御がここに表示されます。</p>
              </div>
            )}
          </div>

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
                      className="ghost-button preview-action-button"
                      href={selectedCase ? renderedPreviewUrl(selectedCase.case_id, selectedCase.workspace_path, preview.path) : '#'}
                      target="_blank"
                      rel="noreferrer"
                      aria-label="別ウィンドウで表示"
                      title="別ウィンドウで表示"
                    >
                      <span className="external-link-icon" aria-hidden="true">
                        <span />
                      </span>
                    </a>
                  </div>
                  {preview.preview_available ? (
                    isMarkdownFile(preview.name, preview.mime_type) ? (
                      <div className="preview-markdown markdown-body">
                        <MarkdownContent content={preview.content || ''} basePath={preview.path} onWorkspaceLinkClick={openWorkspaceFileFromLink} />
                      </div>
                    ) : (
                      <pre>{preview.content}</pre>
                    )
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
    </div>
  );
}