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

/**
 * Empty string = same-origin `/api` (Docker nginx or Vite dev proxy).
 * Set VITE_API_BASE_URL only when the API is on another origin.
 */
function normalizeBase(url) {
  if (url === undefined || url === null || String(url).trim() === '') return '';
  return String(url).replace(/\/$/, '');
}
const ENV_BASE = normalizeBase(import.meta.env.VITE_API_BASE_URL);
const BUILD_KEY = import.meta.env.VITE_MODELFORGE_API_KEY || '';

/** Runtime override from Settings (same-origin default when unset). */
export function getApiBase() {
  try {
    const o = window.localStorage.getItem('modelforge_api_base');
    if (o != null && String(o).trim() !== '') return normalizeBase(o);
  } catch {
    /* ignore */
  }
  return ENV_BASE;
}

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
    const res = await fetch(`${getApiBase()}${path}`, {
      ...options,
      // Ensure POST redirects (e.g. from FastAPI `/infer` -> `/infer/`) are followed.
      redirect: 'follow',
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
  const base = getApiBase();
  const origin = base || (typeof window !== 'undefined' ? window.location.origin : '');
  const wsBase = origin.replace(/^http/, 'ws');
  const key = getApiKey();
  const sep = path.includes('?') ? '&' : '?';
  const suffix = key ? `${sep}api_key=${encodeURIComponent(key)}` : '';
  return new WebSocket(`${wsBase}${path}${suffix}`);
}

async function rawFetchMultipart(path, formData, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const key = getApiKey();
  const headers = {};
  if (key) headers['X-API-Key'] = key;
  try {
    const res = await fetch(`${getApiBase()}${path}`, {
      method: 'POST',
      body: formData,
      redirect: 'follow',
      signal: controller.signal,
      headers,
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

export async function fetchAdapters() {
  // Backend list route is registered at `/api/adapters/` (trailing slash).
  return apiFetch('/api/adapters/');
}

export async function getAdapter(adapterId) {
  return apiFetch(`/api/adapters/${encodeURIComponent(adapterId)}`);
}

export async function deleteAdapter(adapterId) {
  return apiFetch(`/api/adapters/${encodeURIComponent(adapterId)}`, { method: 'DELETE' });
}

export async function rollbackAdapter(adapterId) {
  return apiFetch(`/api/adapters/${encodeURIComponent(adapterId)}/rollback`, { method: 'POST' });
}

export async function serveAdapter(adapterId) {
  return apiFetch(`/api/adapters/${encodeURIComponent(adapterId)}/serve`, { method: 'POST' });
}

export async function compareAdapters(adapterA, adapterB, prompt) {
  const q = prompt ? `?prompt=${encodeURIComponent(prompt)}` : '';
  return apiFetch(
    `/api/adapters/compare/${encodeURIComponent(adapterA)}/${encodeURIComponent(adapterB)}${q}`,
  );
}

export async function cleanupAdapters(params = {}) {
  const sp = new URLSearchParams();
  if (params.older_than_days != null) sp.set('older_than_days', String(params.older_than_days));
  if (params.keep_promoted != null) sp.set('keep_promoted', String(params.keep_promoted));
  const q = sp.toString();
  return apiFetch(`/api/adapters/cleanup${q ? `?${q}` : ''}`, { method: 'POST' });
}

export async function fetchDatasets() {
  // Backend list route is registered at `/api/datasets/` (trailing slash).
  return apiFetch('/api/datasets/');
}

export async function getDataset(datasetId) {
  return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}`);
}

export async function uploadDataset(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    return await rawFetchMultipart('/api/datasets/upload', fd);
  } catch (e) {
    if (e?.status === 401 || e?.status === 403) throw e;
    await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS));
    return rawFetchMultipart('/api/datasets/upload', fd);
  }
}

export async function deleteDataset(datasetId) {
  return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}`, { method: 'DELETE' });
}

export async function getDatasetQuality(datasetId) {
  return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}/quality`);
}

export async function savePairToDataset(datasetId, instruction, response) {
  return apiFetch('/api/datasets/save-pair', {
    method: 'POST',
    body: JSON.stringify({ dataset_id: datasetId, instruction, response }),
  });
}

export async function fetchPresets() {
  return apiFetch('/api/configs/presets');
}

export async function getPreset(name) {
  return apiFetch(`/api/configs/presets/${encodeURIComponent(name)}`);
}

export async function savePreset(name, config) {
  return apiFetch('/api/configs/presets', {
    method: 'POST',
    body: JSON.stringify({ name, config }),
  });
}

export async function deletePreset(name) {
  return apiFetch(`/api/configs/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export async function startEvolutionWithPreset(presetName, overrides = {}) {
  const preset = await getPreset(presetName);
  const base = preset?.config && typeof preset.config === 'object' ? preset.config : {};
  const cfg = { ...base, ...overrides };
  return apiFetch('/api/evolve/start', {
    method: 'POST',
    body: JSON.stringify(cfg),
  });
}

export async function fetchOllamaModelTags() {
  const data = await apiFetch('/api/system/ollama-models');
  return Array.isArray(data?.models) ? data.models : [];
}

export async function compareRuns(runIds) {
  const q = Array.isArray(runIds) ? runIds.join(',') : runIds;
  return apiFetch(`/api/eval/compare-runs?run_ids=${encodeURIComponent(q)}`);
}
