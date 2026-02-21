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
