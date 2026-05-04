/**
 * Tiny API + WebSocket client.
 *
 * Sends `X-API-Key` from `VITE_MODELFORGE_API_KEY` (build-time) or from
 * `localStorage["modelforge_api_key"]` (runtime override). WebSocket
 * clients can't send headers, so the key is appended as `?api_key=...`.
 *
 * Network behaviour:
 * - 15 s default timeout (was 1.5 s — way too aggressive).
 * - 1 retry on `TypeError` / network error with 500 ms backoff.
 * - 401 short-circuits without retry so a bad key surfaces immediately.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const BUILD_KEY = import.meta.env.VITE_MODELFORGE_API_KEY || '';

const DEFAULT_TIMEOUT_MS = 15_000;
const RETRY_BACKOFF_MS = 500;

export function getApiKey() {
  try {
    const fromStorage = window.localStorage.getItem('modelforge_api_key');
    if (fromStorage) return fromStorage;
  } catch {
    /* SSR / private mode */
  }
  return BUILD_KEY;
}

export function setApiKey(key) {
  try {
    if (key) window.localStorage.setItem('modelforge_api_key', key);
    else window.localStorage.removeItem('modelforge_api_key');
  } catch {
    /* ignore */
  }
}

function buildHeaders(extra = {}) {
  const headers = { 'Content-Type': 'application/json', ...extra };
  const key = getApiKey();
  if (key) headers['X-API-Key'] = key;
  return headers;
}

async function rawFetch(path, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...options,
      signal: controller.signal,
      headers: buildHeaders(options.headers || {}),
    });
    if (!res.ok) {
      const error = new Error(`HTTP ${res.status}`);
      error.status = res.status;
      try {
        error.body = await res.json();
      } catch {
        error.body = null;
      }
      throw error;
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export async function apiFetch(path, options = {}, { timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  try {
    return await rawFetch(path, options, timeoutMs);
  } catch (error) {
    if (error?.status === 401 || error?.status === 403) throw error;
    if (error?.name === 'AbortError') throw error;
    await new Promise((resolve) => setTimeout(resolve, RETRY_BACKOFF_MS));
    return rawFetch(path, options, timeoutMs);
  }
}

export function wsConnect(path) {
  const wsBase = BASE.replace(/^http/, 'ws');
  const key = getApiKey();
  const sep = path.includes('?') ? '&' : '?';
  const suffix = key ? `${sep}api_key=${encodeURIComponent(key)}` : '';
  return new WebSocket(`${wsBase}${path}${suffix}`);
}
