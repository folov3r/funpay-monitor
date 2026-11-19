export interface Health {
  status: string;
  version: string;
  database: string;
  scheduler: boolean;
}

export interface Server {
  id: number;
  funpay_server_id: number;
  name: string;
}

export interface Category {
  id: number;
  funpay_id: number;
  type: string;
  title: string;
  game_title: string | null;
  url_path: string;
  server_label: string | null;
  is_active: boolean;
  last_parsed_at: string | null;
  created_at: string;
  servers: Server[];
}

export interface PriceSummary {
  min_price: string;
  median_price: string;
  offer_count: number;
}

export interface Offer {
  id: number;
  seller_id: number | null;
  seller_name: string | null;
  amount: string | null;
  price: string;
  currency: string;
  item_type: string | null;
  method: string | null;
  title: string | null;
  is_online: boolean;
  is_promo: boolean;
  parsed_at: string;
}

export interface HistoryPoint {
  captured_at: string;
  min_price: string;
  median_price: string;
  offer_count: number;
}

export interface ImportResult {
  category: Category;
  item_types: string[];
  offers_found: number;
  snapshots_created: number;
  summary: PriceSummary | null;
}

export type AlertMode = "abs" | "pct" | "lowest";

export interface Subscription {
  id: number;
  category_id: number;
  category_title: string;
  category_path: string;
  server_id: number | null;
  server_name: string | null;
  item_type: string | null;
  query: string | null;
  mode: AlertMode;
  threshold: string | null;
  is_active: boolean;
  created_at: string;
}

export interface SubscriptionStats {
  subscription: Subscription;
  summary: PriceSummary | null;
  history: HistoryPoint[];
  cheapest: Offer[];
}

export interface ParseRun {
  category_id: number;
  category_title: string;
  category_path: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  offers_found: number;
  error_text: string | null;
}

export interface Status {
  categories: number;
  active_categories: number;
  users: number;
  active_subscriptions: number;
  offers: number;
  parse_runs: ParseRun[];
  scheduler_state: "off" | "active" | "paused" | "running";
  next_run_at: string | null;
  last_run_at: string | null;
  interval_minutes: number;
}

export interface Notification {
  id: number;
  subscription_id: number;
  category_id: number;
  category_title: string;
  mode: AlertMode;
  price: string;
  sent_at: string;
}

export interface ReparseResult {
  category_id: number;
  title: string;
  status: string;
  offers_found: number;
  snapshots_created: number;
  alerts_sent: number;
  error_text: string | null;
}

export interface SubscriptionInput {
  category_id: number;
  server_id: number | null;
  mode: AlertMode;
  threshold: string | null;
  item_type: string | null;
  query: string | null;
}
