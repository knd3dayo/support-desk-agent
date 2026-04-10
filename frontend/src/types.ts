export type CaseSummary = {
  case_id: string;
  workspace_path: string;
  updated_at: string;
  message_count: number;
};

export type ChatMessage = {
  role: string;
  content: string;
  trace_id?: string | null;
  event?: string | null;
  created_at?: string | null;
};

export type ChatHistoryResponse = {
  case_id: string;
  workspace_path: string;
  messages: ChatMessage[];
};

export type WorkspaceEntry = {
  name: string;
  path: string;
  kind: 'file' | 'directory' | string;
  size?: number | null;
};

export type WorkspaceBrowseResponse = {
  case_id: string;
  workspace_path: string;
  current_path: string;
  entries: WorkspaceEntry[];
};

export type WorkspaceFileResponse = {
  case_id: string;
  workspace_path: string;
  path: string;
  name: string;
  mime_type?: string | null;
  preview_available: boolean;
  truncated: boolean;
  content?: string | null;
};

export type WorkspaceUploadResponse = {
  case_id: string;
  workspace_path: string;
  path: string;
  size: number;
};

export type RuntimeEnvelope = {
  case_id: string;
  trace_id?: string | null;
  workflow_kind?: string | null;
  workflow_label?: string | null;
  execution_mode?: string | null;
  plan_summary?: string | null;
  plan_steps: string[];
  requires_approval?: boolean | null;
  requires_customer_input?: boolean | null;
  state: Record<string, unknown>;
};

export type InitCaseResponse = {
  case_id: string;
  case_path: string;
};