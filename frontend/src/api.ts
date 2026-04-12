import type {
  CaseSummary,
  ChatHistoryResponse,
  ControlCatalogResponse,
  GenerateReportResponse,
  InitCaseResponse,
  RuntimeAuditResponse,
  RuntimeEnvelope,
  UiConfigResponse,
  WorkspaceBrowseResponse,
  WorkspaceFileResponse,
  WorkspaceUploadResponse,
} from './types';

const AUTH_TOKEN_STORAGE_KEY = 'support-ope-agents-auth-token';

type TicketIdOptions = {
  externalTicketId?: string;
  internalTicketId?: string;
};

type LangChainMessage = {
  type: string;
  data: {
    content: unknown;
    additional_kwargs?: Record<string, unknown>;
    response_metadata?: Record<string, unknown>;
    name?: string | null;
    id?: string | null;
    tool_call_id?: string | null;
  };
};

function getAuthHeaders(): Record<string, string> {
  const token = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)?.trim();
  if (!token) {
    return {};
  }
  return {
    Authorization: `Bearer ${token}`,
  };
}

export function getSavedAuthToken(): string {
  return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? '';
}

export function saveAuthToken(token: string): void {
  const normalized = token.trim();
  if (!normalized) {
    window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, normalized);
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

export function listCases(): Promise<CaseSummary[]> {
  return requestJson<CaseSummary[]>('/cases');
}

export function loadUiConfig(): Promise<UiConfigResponse> {
  return requestJson<UiConfigResponse>('/ui-config');
}

export function loadControlCatalog(): Promise<ControlCatalogResponse> {
  return requestJson<ControlCatalogResponse>('/control-catalog');
}

export function createCase(prompt: string): Promise<InitCaseResponse> {
  return requestJson<InitCaseResponse>('/cases', {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  });
}

export function loadHistory(caseId: string, workspacePath: string): Promise<ChatHistoryResponse> {
  const params = new URLSearchParams({ workspace_path: workspacePath });
  return requestJson<ChatHistoryResponse>(`/cases/${caseId}/history?${params.toString()}`);
}

export function browseWorkspace(caseId: string, workspacePath: string, path = '.'): Promise<WorkspaceBrowseResponse> {
  const params = new URLSearchParams({ workspace_path: workspacePath, path });
  return requestJson<WorkspaceBrowseResponse>(`/cases/${caseId}/workspace?${params.toString()}`);
}

export function loadFile(
  caseId: string,
  workspacePath: string,
  path: string,
  options?: { maxChars?: number }
): Promise<WorkspaceFileResponse> {
  const params = new URLSearchParams({ workspace_path: workspacePath, path });
  if (options?.maxChars) {
    params.set('max_chars', String(options.maxChars));
  }
  return requestJson<WorkspaceFileResponse>(`/cases/${caseId}/workspace/file?${params.toString()}`);
}

export function rawFileUrl(caseId: string, workspacePath: string, path: string): string {
  const params = new URLSearchParams({ workspace_path: workspacePath, path });
  return `/cases/${caseId}/workspace/raw?${params.toString()}`;
}

export function renderedPreviewUrl(caseId: string, workspacePath: string, path: string): string {
  const params = new URLSearchParams({ preview: '1', case_id: caseId, workspace_path: workspacePath, path });
  return `/?${params.toString()}`;
}

export async function loadRawFileBlob(caseId: string, workspacePath: string, path: string): Promise<Blob> {
  const response = await fetch(rawFileUrl(caseId, workspacePath, path), {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }

  return await response.blob();
}

export async function uploadWorkspaceFile(
  caseId: string,
  workspacePath: string,
  relativeDir: string,
  file: File
): Promise<WorkspaceUploadResponse> {
  const formData = new FormData();
  formData.append('workspace_path', workspacePath);
  formData.append('relative_dir', relativeDir);
  formData.append('file', file);

  const response = await fetch(`/cases/${caseId}/workspace/upload`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`);
  }

  return (await response.json()) as WorkspaceUploadResponse;
}

export function downloadWorkspaceUrl(caseId: string, workspacePath: string): string {
  const params = new URLSearchParams({ workspace_path: workspacePath });
  return `/cases/${caseId}/workspace/download?${params.toString()}`;
}

export function generateReport(
  caseId: string,
  workspacePath: string,
  traceId: string,
  checklist: string[] = []
): Promise<GenerateReportResponse> {
  return requestJson<GenerateReportResponse>(`/cases/${caseId}/report`, {
    method: 'POST',
    body: JSON.stringify({
      workspace_path: workspacePath,
      trace_id: traceId,
      checklist,
    }),
  });
}

export function loadRuntimeAudit(caseId: string, workspacePath: string, traceId: string): Promise<RuntimeAuditResponse> {
  const params = new URLSearchParams({ workspace_path: workspacePath, trace_id: traceId });
  return requestJson<RuntimeAuditResponse>(`/cases/${caseId}/runtime-audit?${params.toString()}`);
}

export function sendAction(
  prompt: string,
  workspacePath: string,
  caseId: string,
  ticketIds?: TicketIdOptions,
  conversationMessages: LangChainMessage[] = []
): Promise<RuntimeEnvelope> {
  return requestJson<RuntimeEnvelope>('/action', {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      workspace_path: workspacePath,
      case_id: caseId,
      external_ticket_id: ticketIds?.externalTicketId,
      internal_ticket_id: ticketIds?.internalTicketId,
      conversation_messages: conversationMessages,
    }),
  });
}

export function resumeCustomerInput(
  caseId: string,
  traceId: string,
  workspacePath: string,
  additionalInput: string,
  answerKey?: string,
  ticketIds?: TicketIdOptions
): Promise<RuntimeEnvelope> {
  return requestJson<RuntimeEnvelope>('/resume-customer-input', {
    method: 'POST',
    body: JSON.stringify({
      case_id: caseId,
      trace_id: traceId,
      workspace_path: workspacePath,
      additional_input: additionalInput,
      answer_key: answerKey ?? null,
      external_ticket_id: ticketIds?.externalTicketId,
      internal_ticket_id: ticketIds?.internalTicketId,
    }),
  });
}