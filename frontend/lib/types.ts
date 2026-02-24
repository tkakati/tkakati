export type Post = {
  id: number;
  post_url: string;
  title: string;
  company: string | null;
  seniority: string | null;
  location: string | null;
  remote: boolean;
  query_used: string;
  status: PostStatus;
  first_seen: string;
  created_at: string;
};

export const POST_STATUSES = [
  "no action",
  "reached out",
  "responded",
  "chatted",
  "referred",
] as const;

export type PostStatus = (typeof POST_STATUSES)[number];

export type Run = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  inserted: number;
  skipped: number;
  error: string | null;
};

export type PaginatedPosts = {
  items: Post[];
  page: number;
  page_size: number;
  total: number;
};

export type CollectorRunResponse = {
  run_id: number;
  status: string;
  inserted: number;
  skipped: number;
  error: string | null;
};

export type CollectorRunRequest = {
  designations?: string[];
  locations?: string[];
  last_days?: number;
};

export type HiringStrictness = "low" | "medium" | "high";

export type Signal = {
  id: number;
  company: string | null;
  role: string | null;
  seniority: string | null;
  is_hiring: boolean;
  signal_strength: number;
  signal_type: string;
  confidence: number;
  company_source: string;
  company_confidence: number;
  hiring_confidence: number;
  role_match_score: number;
  reasoning: string | null;
  review_status: string;
  review_label: string | null;
  source_url: string;
  timestamp: string;
};

export type PaginatedSignals = {
  items: Signal[];
  page: number;
  page_size: number;
  total: number;
  total_base: number;
};

export type SignalMetrics = {
  strong_signals: number;
  medium_confidence: number;
  filtered: number;
  common_filter_reasons: Array<{ reason: string; count: number }>;
  false_positive_trends: Array<{ day: string; count: number }>;
  emerging_companies: Array<{ company: string; signals: number; avg_strength: number }>;
  hidden_hiring_clusters: Array<{ company: string; role: string; signals: number; avg_strength: number }>;
};

export type ReviewAction = "approve" | "reject" | "relabel";
