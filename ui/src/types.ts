export interface Actor {
  name: string;
  person?: string;
  role: "reader" | "writer" | "reviewer" | "admin";
  kind: "agent" | "human";
  clearance: string;
}
export interface Page {
  id: string;
  type: string;
  title: string;
  summary: string;
  status: string;
  updated?: string;
  created?: string;
  sensitivity?: string;
  body_md?: string;
  version?: string;
  tags?: string[];
  sources?: string[];
  aliases?: string[];
  relations?: Record<string, string[]>;
  category?: string;
  level?: string;
  lifecycle?: string;
  applies_to?: string[];
  origin?: string;
  priority?: number;
  owner?: string;
  enforced_by?: string[];
  verified_by?: string;
  extra?: Record<string, unknown>;
  neighbors?: Graph;
  history?: History[];
  delivered?: number;
  opened?: number;
}
export interface History {
  commit: string;
  author: string;
  date: string;
  message: string;
}
export interface List<T> {
  items: T[];
  next_cursor?: string | null;
}
export interface Issue {
  code: string;
  severity: string;
  message: string;
  page?: string;
  hint?: string;
}
export interface Validation {
  errors: Issue[];
  warnings: Issue[];
}
export interface Promotion {
  id: string;
  level: "must" | "should";
  priority?: number;
  owner?: string;
  applies_to?: string[];
  enforced_by?: string[];
}
export interface AcceptBody {
  promote: Promotion[];
  deprecate: { id: string; reason: string }[];
}
export interface Plan {
  proposal?: string;
  summary: string;
  items: {
    n?: number;
    action: string;
    target?: string;
    thesis?: string;
    level?: string;
    reason?: string;
    confidence?: number;
    scopes?: string[];
  }[];
  questions: { id: string; text: string; options: string[] }[];
  assumptions: string[];
  impact?: { profiles?: string[]; pages?: (Page | string)[] };
  needs_double_confirm?: boolean;
  accept_body?: AcceptBody;
  cancelled?: boolean;
}
export interface Proposal {
  pid: string;
  title: string;
  description: string;
  status: string;
  kind: string;
  author: string;
  author_identity?: string;
  last_editor?: string;
  updated_at: string;
  created_at: string;
  review_comment?: string;
  pages?: Page[];
  validation?: Validation;
  notes?: Plan;
}
export interface Diff {
  pages: {
    id: string;
    change: string;
    frontmatter_diff: { field: string; before: unknown; after: unknown }[];
    sections: { heading: string; change: string; unified_diff: string }[];
    warnings: Issue[];
  }[];
  validation: Validation;
  edges_added: Edge[];
  edges_removed: Edge[];
}
export interface Impact {
  pages: Page[];
  rules: Page[];
  profiles: string[];
}
export interface Finding {
  id: string;
  kind: string;
  severity: string;
  status: string;
  summary: string;
  explanation: string;
  pages: string[];
  evidence: { page: string; quote: string }[];
  proposal_pid?: string;
  created_at: string;
  reason?: string;
}
export interface Edge {
  src: string;
  dst: string;
  rel: string;
  kind?: string;
}
export interface Graph {
  nodes: (Page & { depth?: number })[];
  edges: Edge[];
}
export interface Profile {
  id: string;
  title: string;
  scopes: string[];
  budget_tokens: number;
}
export interface Session {
  id: string;
  owner: string;
  bind: { type: string; id: string };
  profile?: string;
  plan?: Plan;
  messages: { role: string; text: string; plan?: Plan; created_at: string }[];
  updated_at: string;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  updated_at: string;
  error?: string;
  payload: Record<string, unknown>;
  progress: Record<string, unknown>;
  proposals?: string[];
}
export interface RawFile {
  path: string;
  sha256: string;
  size?: number;
  bytes?: number;
  original_name?: string;
  note?: string;
  ingested?: boolean;
  sources?: string[];
  extraction?: {
    status: string;
    pages?: number;
    chars?: number;
    error?: string;
  };
}
export interface Schema {
  page_types: Record<
    string,
    {
      type: string;
      prefix: string;
      title_ru: string;
      required_sections: string[];
      extra_fields: Record<
        string,
        { type: string; required: boolean; enum: string[]; default?: unknown }
      >;
    }
  >;
  tags: string[];
  scopes: string[];
}
