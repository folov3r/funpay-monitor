import type {
  Category,
  Health,
  HistoryPoint,
  ImportResult,
  Notification,
  Offer,
  PriceSummary,
  ReparseResult,
  Status,
  Subscription,
  SubscriptionInput,
  SubscriptionStats,
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (window.location.protocol === "tauri:" || window.location.hostname === "tauri.localhost"
    ? "http://127.0.0.1:8765/api"
    : "/api");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // Keep the status text when the body is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const result = search.toString();
  return result ? `?${result}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  status: () => request<Status>("/status"),
  categories: () => request<Category[]>("/categories"),
  importCategory: (url: string) =>
    request<ImportResult>("/categories/import", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  summary: (categoryId: number, filters: { server_id?: number | null; item_type?: string; query?: string }) =>
    request<PriceSummary | null>(`/categories/${categoryId}/summary${query(filters)}`),
  offers: (
    categoryId: number,
    filters: { server_id?: number | null; item_type?: string; query?: string; limit?: number },
  ) => request<Offer[]>(`/categories/${categoryId}/offers${query(filters)}`),
  history: (
    categoryId: number,
    filters: { server_id?: number | null; item_type?: string; query?: string; days?: number },
  ) => request<HistoryPoint[]>(`/categories/${categoryId}/history${query(filters)}`),
  subscriptions: () => request<Subscription[]>("/subscriptions"),
  createSubscription: (payload: SubscriptionInput) =>
    request<Subscription>("/subscriptions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteSubscription: (id: number) =>
    request<void>(`/subscriptions/${id}`, { method: "DELETE" }),
  subscriptionStats: (id: number, days = 7) =>
    request<SubscriptionStats>(`/subscriptions/${id}/stats${query({ days })}`),
  notifications: (limit = 50) => request<Notification[]>(`/notifications${query({ limit })}`),
  reparse: (categoryId: number) =>
    request<ReparseResult>(`/categories/${categoryId}/reparse`, { method: "POST" }),
};
