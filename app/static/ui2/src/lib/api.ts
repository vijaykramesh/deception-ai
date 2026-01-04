export const API_BASE = (globalThis as any).__API_BASE__ || '';

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

