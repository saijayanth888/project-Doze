/**
 * Compute pace + ETA for a running campaign from its results array.
 * Single source of truth used by both the /campaigns banner and the
 * Evolution Status widget on /dashboard.
 *
 * @param {Object} status — payload from /api/campaigns/status.
 * @returns {{ paceSeconds: number|null, remaining: number, etaSeconds: number|null, doneByLabel: string|null }}
 */
export function campaignEta(status) {
  if (!status) return { paceSeconds: null, remaining: 0, etaSeconds: null, doneByLabel: null };
  const total = status.total_experiments || 0;
  const completed = status.completed || 0;
  const failed = status.failed || 0;
  const remaining = Math.max(0, total - completed - failed);

  const finishedDurations = (status.results || [])
    .map((r) => Number(r.duration ?? r.duration_seconds))
    .filter((n) => Number.isFinite(n) && n > 0);

  const paceSeconds =
    finishedDurations.length > 0
      ? finishedDurations.reduce((a, b) => a + b, 0) / finishedDurations.length
      : status.pace_avg_seconds ?? null;

  const etaSeconds =
    paceSeconds && remaining > 0 ? paceSeconds * remaining : null;

  let doneByLabel = null;
  if (etaSeconds && etaSeconds > 0) {
    const t = new Date(Date.now() + etaSeconds * 1000);
    doneByLabel = t.toLocaleString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      day: '2-digit',
      month: 'short',
    });
  }

  return { paceSeconds, remaining, etaSeconds, doneByLabel };
}

export function fmtDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}
