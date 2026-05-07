import { useCallback, useEffect, useState } from 'react';
import { Play, ChevronDown, ChevronRight, FlaskConical, Pause, Square, Download } from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import { CONCEPT_INFO } from '../data/benchmarkInfo';
import InfoTooltip from '../components/shared/InfoTooltip';
import LoadingSkeleton from '../components/shared/LoadingSkeleton';
import { useToast } from '../context/ToastContext';

function humanizeCampaignId(id) {
  return String(id)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function ExperimentRow({ exp }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,2fr) 120px 120px',
        gap: 10,
        padding: '6px 12px',
        borderBottom: `1px solid ${C.border}`,
        fontFamily: F.mono,
        fontSize: 11,
        color: C.txtS,
      }}
    >
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          color: C.txtP,
        }}
      >
        {exp.model || exp.model_id || exp.base_model || '—'}
      </span>
      <span style={{ color: C.txtM }}>
        {exp.method || (exp.eval_only ? 'baseline' : 'sequential')}
      </span>
      <span style={{ color: C.txtM, textAlign: 'right' }}>
        {exp.max_generations != null ? `${exp.max_generations} gen` : '—'}
      </span>
    </div>
  );
}

// ---- Status badge helpers ----
const STATUS_COLORS = {
  running:   { bg: 'rgba(34,197,94,0.15)',  text: '#22c55e', dot: '#22c55e'  },
  ensuring:  { bg: 'rgba(56,189,248,0.15)', text: '#38bdf8', dot: '#38bdf8'  },
  paused:    { bg: 'rgba(234,179,8,0.15)',  text: '#eab308', dot: '#eab308'  },
  stopping:  { bg: 'rgba(249,115,22,0.15)', text: '#f97316', dot: '#f97316'  },
  completed: { bg: 'rgba(34,197,94,0.12)',  text: '#22c55e', dot: '#22c55e'  },
  failed:    { bg: 'rgba(239,68,68,0.15)',  text: '#ef4444', dot: '#ef4444'  },
  pending:   { bg: 'rgba(148,163,184,0.1)', text: '#94a3b8', dot: '#94a3b8'  },
  idle:      { bg: 'rgba(148,163,184,0.1)', text: '#94a3b8', dot: '#94a3b8'  },
};

function StatusBadge({ status }) {
  const col = STATUS_COLORS[status] || STATUS_COLORS.idle;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '2px 8px',
        borderRadius: 99,
        background: col.bg,
        color: col.text,
        fontFamily: F.mono,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: col.dot,
          flexShrink: 0,
        }}
      />
      {status}
    </span>
  );
}

// ---- Extract model name from live-result config ----
function extractModel(config) {
  if (!config) return '—';
  return config.model_id || config.base_model || config.model || '—';
}

// ---- Active Campaign Banner ----
function ActiveCampaignBanner({ status, onPause, onResume, onStop, onExport }) {
  if (!status || status.status === 'idle') return null;

  const {
    plan_id,
    status: st,
    current_experiment = 0,
    total_experiments = 0,
    completed = 0,
    failed = 0,
    results = [],
    ensure_progress: ensureProgress = [],
  } = status;

  const done = completed + failed;
  const progress = total_experiments > 0 ? done / total_experiments : 0;

  // ETA calc
  const withDuration = results.filter(
    (r) => r.status === 'completed' && r.duration_seconds != null,
  );
  let etaLabel = 'ETA: pending first experiment';
  if (withDuration.length > 0) {
    const avg = withDuration.reduce((s, r) => s + r.duration_seconds, 0) / withDuration.length;
    const remaining = total_experiments - done;
    const totalSec = avg * remaining;
    const hours = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    etaLabel = `~${hours}h ${mins}m remaining`;
  }

  const isRunning = st === 'running';
  const isPaused = st === 'paused';

  return (
    <div
      style={{
        background: 'var(--bg-card, #111827)',
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      {/* Banner header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '14px 18px',
          flexWrap: 'wrap',
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
          <StatusBadge status={st} />
          <span
            style={{
              fontFamily: F.mono,
              fontSize: 12,
              color: C.txtP,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {plan_id ? humanizeCampaignId(plan_id) : '—'}
          </span>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, whiteSpace: 'nowrap' }}>
            Experiment {current_experiment + 1} of {total_experiments}
          </span>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, whiteSpace: 'nowrap' }}>
            ✓ {completed} &nbsp;✗ {failed}
          </span>
        </div>

        {/* Control buttons */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
          <button
            type="button"
            disabled={!isRunning}
            onClick={onPause}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 12px',
              background: isRunning ? 'rgba(234,179,8,0.15)' : 'rgba(255,255,255,0.04)',
              color: isRunning ? '#eab308' : C.txtM,
              border: `1px solid ${isRunning ? 'rgba(234,179,8,0.4)' : C.border}`,
              borderRadius: 6,
              cursor: isRunning ? 'pointer' : 'not-allowed',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 600,
              opacity: isRunning ? 1 : 0.45,
            }}
          >
            <Pause size={12} />
            Pause
          </button>

          <button
            type="button"
            disabled={!isPaused}
            onClick={onResume}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 12px',
              background: isPaused ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.04)',
              color: isPaused ? '#22c55e' : C.txtM,
              border: `1px solid ${isPaused ? 'rgba(34,197,94,0.35)' : C.border}`,
              borderRadius: 6,
              cursor: isPaused ? 'pointer' : 'not-allowed',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 600,
              opacity: isPaused ? 1 : 0.45,
            }}
          >
            <Play size={12} fill="currentColor" />
            Resume
          </button>

          <button
            type="button"
            disabled={st === 'stopping' || st === 'idle'}
            onClick={onStop}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 12px',
              background: 'rgba(239,68,68,0.1)',
              color: '#ef4444',
              border: '1px solid rgba(239,68,68,0.35)',
              borderRadius: 6,
              cursor: (st === 'stopping' || st === 'idle') ? 'not-allowed' : 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 600,
              opacity: (st === 'stopping' || st === 'idle') ? 0.45 : 1,
            }}
          >
            <Square size={12} fill="currentColor" />
            Stop
          </button>

          <button
            type="button"
            onClick={() => onExport(plan_id)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 12px',
              background: 'rgba(255,255,255,0.05)',
              color: C.txtM,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              cursor: 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            <Download size={12} />
            Export
          </button>
        </div>
      </div>

      {/* Progress bar + ETA */}
      <div style={{ padding: '10px 18px', borderBottom: `1px solid ${C.border}` }}>
        <div
          style={{
            height: 6,
            background: 'rgba(255,255,255,0.06)',
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 6,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${Math.min(progress * 100, 100)}%`,
              background: C.acc || '#76b900',
              borderRadius: 99,
              transition: 'width 0.4s ease',
            }}
          />
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
          {Math.round(progress * 100)}% complete &nbsp;·&nbsp; {etaLabel}
        </div>
      </div>

      {/* Pre-flight HF download progress (ensuring phase) */}
      {st === 'ensuring' && ensureProgress.length > 0 ? (
        <div style={{ padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
          <div
            style={{
              padding: '6px 18px 4px',
              fontFamily: F.mono,
              fontSize: 9,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: C.txtM,
            }}
          >
            Pre-flight: downloading model weights ({
              ensureProgress.filter((e) => e.status === 'done').length
            } / {ensureProgress.length})
          </div>
          {ensureProgress.map((e) => {
            const ic =
              e.status === 'done' ? '✓'
              : e.status === 'downloading' ? '↓'
              : e.status === 'error' ? '✗'
              : '·';
            const col =
              e.status === 'done' ? '#22c55e'
              : e.status === 'downloading' ? '#38bdf8'
              : e.status === 'error' ? '#ef4444'
              : C.txtM;
            const mb = e.downloaded_bytes
              ? ` · ${(e.downloaded_bytes / (1024 * 1024)).toFixed(0)} MB`
              : '';
            return (
              <div
                key={e.repo_id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '24px minmax(0,1fr) auto',
                  gap: 8,
                  padding: '3px 18px',
                  fontFamily: F.mono,
                  fontSize: 11,
                  color: C.txtS,
                  alignItems: 'center',
                }}
              >
                <span style={{ color: col, textAlign: 'center', fontWeight: 700 }}>{ic}</span>
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    color: C.txtP,
                  }}
                >
                  {e.repo_id}
                </span>
                <span style={{ color: C.txtM, fontSize: 10 }}>
                  {e.status}{mb}
                  {e.error ? ` · ${e.error}` : ''}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Per-experiment rows */}
      {results.length > 0 ? (
        <div>
          {/* Column headers */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '32px minmax(0,2fr) 100px 80px 70px 70px',
              gap: 8,
              padding: '6px 14px',
              background: 'rgba(255,255,255,0.02)',
              borderBottom: `1px solid ${C.border}`,
              fontFamily: F.mono,
              fontSize: 9,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: C.txtM,
            }}
          >
            <span>#</span>
            <span>Model</span>
            <span>Method</span>
            <span>Status</span>
            <span style={{ textAlign: 'right' }}>Score</span>
            <span style={{ textAlign: 'right' }}>Duration</span>
          </div>
          {results.map((r, i) => {
            const col = STATUS_COLORS[r.status] || STATUS_COLORS.idle;
            const avgScore =
              r.scores && typeof r.scores === 'object'
                ? Object.values(r.scores).filter((v) => typeof v === 'number')
                : [];
            const scoreDisplay =
              avgScore.length > 0
                ? (avgScore.reduce((a, b) => a + b, 0) / avgScore.length).toFixed(3)
                : '—';
            const durDisplay =
              r.duration_seconds != null
                ? r.duration_seconds < 60
                  ? `${Math.round(r.duration_seconds)}s`
                  : `${Math.floor(r.duration_seconds / 60)}m${Math.round(r.duration_seconds % 60)}s`
                : '—';
            return (
              <div
                key={r.experiment_index != null ? r.experiment_index : i}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '32px minmax(0,2fr) 100px 80px 70px 70px',
                  gap: 8,
                  padding: '6px 14px',
                  borderBottom: `1px solid ${C.border}`,
                  fontFamily: F.mono,
                  fontSize: 11,
                  color: C.txtS,
                  alignItems: 'center',
                }}
              >
                <span style={{ color: C.txtM }}>{(r.experiment_index ?? i) + 1}</span>
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    color: C.txtP,
                  }}
                >
                  {extractModel(r.config)}
                </span>
                <span style={{ color: C.txtM }}>
                  {r.config?.method || r.config?.training_method || '—'}
                </span>
                <span>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      padding: '1px 6px',
                      borderRadius: 99,
                      background: col.bg,
                      color: col.text,
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                    }}
                  >
                    {r.status || 'pending'}
                  </span>
                </span>
                <span style={{ color: C.txtM, textAlign: 'right' }}>{scoreDisplay}</span>
                <span style={{ color: C.txtM, textAlign: 'right' }}>{durDisplay}</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function CampaignCard({ campaign, onStart, isBlocked }) {
  const [open, setOpen] = useState(false);

  const experiments = campaign.experiments || [];
  const name = campaign.name || humanizeCampaignId(campaign.id || campaign.campaign_id || '');
  const description = campaign.description || '';
  const expCount = experiments.length;
  const campaignId = campaign.id || campaign.campaign_id || '';

  return (
    <div
      style={{
        background: 'var(--bg-card, #111827)',
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      {/* Card header */}
      <div style={{ padding: '16px 18px 14px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontFamily: F.display || F.ui,
                fontSize: 16,
                fontWeight: 700,
                color: 'var(--text-primary, #f1f5f9)',
                marginBottom: 4,
              }}
            >
              {name}
            </div>
            {description ? (
              <div
                style={{
                  fontFamily: F.ui,
                  fontSize: 12,
                  color: 'var(--text-secondary, #94a3b8)',
                  lineHeight: 1.55,
                  marginBottom: 6,
                }}
              >
                {description}
              </div>
            ) : null}
            <div
              style={{
                fontFamily: F.mono,
                fontSize: 11,
                color: C.txtM,
              }}
            >
              {expCount} experiment{expCount !== 1 ? 's' : ''}
            </div>
          </div>

          <button
            type="button"
            disabled={isBlocked}
            onClick={() => onStart(campaignId)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 14px',
              background: isBlocked ? 'rgba(255,255,255,0.06)' : (C.acc || '#76b900'),
              color: isBlocked ? C.txtM : '#000',
              border: 'none',
              borderRadius: 6,
              cursor: isBlocked ? 'not-allowed' : 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 700,
              whiteSpace: 'nowrap',
              flexShrink: 0,
              opacity: isBlocked ? 0.5 : 1,
            }}
          >
            <Play size={12} fill="currentColor" />
            {isBlocked ? 'Campaign in progress' : 'Start Campaign'}
          </button>
        </div>
      </div>

      {/* Collapsible experiments */}
      {expCount > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              width: '100%',
              padding: '8px 18px',
              background: 'rgba(255,255,255,0.025)',
              border: 'none',
              borderTop: `1px solid ${C.border}`,
              cursor: 'pointer',
              color: C.txtM,
              fontFamily: F.mono,
              fontSize: 11,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              textAlign: 'left',
            }}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {open ? 'Hide' : 'Show'} experiments
          </button>

          {open ? (
            <div>
              {/* Column headers */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0,2fr) 120px 120px',
                  gap: 10,
                  padding: '6px 12px',
                  borderBottom: `1px solid ${C.border}`,
                  background: 'rgba(255,255,255,0.02)',
                  fontFamily: F.mono,
                  fontSize: 9,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: C.txtM,
                }}
              >
                <span>Model</span>
                <span>Method</span>
                <span style={{ textAlign: 'right' }}>Max Gen</span>
              </div>
              {experiments.map((exp, i) => (
                <ExperimentRow key={exp.experiment_id || exp.id || i} exp={exp} />
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export default function CampaignPage() {
  const [campaigns, setCampaigns] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState({ status: 'idle', results: [] });
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/api/campaigns');
      setCampaigns(Array.isArray(data) ? data : data?.campaigns || []);
    } catch (e) {
      toast.show(
        `Failed to load campaigns: ${e?.message || 'network error'}`,
        'danger',
      );
      setCampaigns([]);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const pollStatus = useCallback(async () => {
    try {
      const data = await apiFetch('/api/campaigns/status');
      setStatus(data || { status: 'idle', results: [] });
    } catch {
      /* silently keep last */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    pollStatus();
  }, [pollStatus]);

  useEffect(() => {
    if (status.status === 'idle') return;
    const iv = setInterval(pollStatus, 10_000);
    return () => clearInterval(iv);
  }, [status.status, pollStatus]);

  const startCampaign = useCallback(async (campaignId) => {
    try {
      await apiFetch(`/api/campaigns/${campaignId}/start`, { method: 'POST' });
      toast.show(`Campaign "${humanizeCampaignId(campaignId)}" started`, 'success');
      pollStatus();
    } catch (err) {
      if (err.status === 409 || /already running/i.test(String(err.body?.detail || err.message || ''))) {
        toast.show('A campaign is already running — pause/stop it first', 'danger');
      } else {
        toast.show(`Failed to start: ${err.message}`, 'danger');
      }
    }
  }, [toast, pollStatus]);

  const handlePause = useCallback(async () => {
    try {
      await apiFetch('/api/campaigns/pause', { method: 'POST' });
      toast.show('Paused', 'success');
      pollStatus();
    } catch (err) {
      toast.show(`Failed to pause: ${err.message}`, 'danger');
    }
  }, [toast, pollStatus]);

  const handleResume = useCallback(async () => {
    try {
      await apiFetch('/api/campaigns/resume', { method: 'POST' });
      toast.show('Resumed', 'success');
      pollStatus();
    } catch (err) {
      toast.show(`Failed to resume: ${err.message}`, 'danger');
    }
  }, [toast, pollStatus]);

  const handleStop = useCallback(async () => {
    try {
      await apiFetch('/api/campaigns/stop', { method: 'POST' });
      toast.show('Stopping — will exit at the next benchmark boundary (usually 1–10 min).', 'success');
      pollStatus();
    } catch (err) {
      toast.show(`Failed to stop: ${err.message}`, 'danger');
    }
  }, [toast, pollStatus]);

  const exportResults = useCallback(async (planId) => {
    try {
      const data = await apiFetch(`/api/campaigns/${planId}/results`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `campaign-${planId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.show(`Failed to export: ${err.message}`, 'danger');
    }
  }, [toast]);

  const isBlocked =
    status.status === 'running' ||
    status.status === 'ensuring' ||
    status.status === 'paused' ||
    status.status === 'stopping';

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Page heading */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <FlaskConical size={24} color={C.acc || '#76b900'} style={{ marginTop: 3, flexShrink: 0 }} />
        <div>
          <h1
            style={{
              fontFamily: F.display || F.ui,
              fontSize: 26,
              fontWeight: 700,
              color: 'var(--text-primary, #f1f5f9)',
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            Research Campaigns
            <InfoTooltip info={CONCEPT_INFO.ept} />
          </h1>
          <p
            style={{
              fontFamily: F.ui,
              fontSize: 13,
              color: 'var(--text-secondary, #94a3b8)',
              margin: '6px 0 0',
              lineHeight: 1.6,
              maxWidth: 680,
            }}
          >
            A <strong style={{ color: 'var(--text-primary, #f1f5f9)' }}>Research Campaign</strong> is a
            pre-configured sequence of evolution experiments designed to systematically improve a model
            across multiple tasks. Each campaign bundles a set of (model, method, generations) tuples
            that run in order, producing a lineage you can inspect and promote.
          </p>
        </div>
      </div>

      {/* Active campaign banner */}
      <ActiveCampaignBanner
        status={status}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
        onExport={exportResults}
      />

      {/* Campaign list */}
      {loading ? (
        <LoadingSkeleton rows={4} height={80} />
      ) : campaigns && campaigns.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {campaigns.map((c, i) => (
            <CampaignCard
              key={c.id || c.campaign_id || i}
              campaign={c}
              onStart={startCampaign}
              isBlocked={isBlocked}
            />
          ))}
        </div>
      ) : (
        <div
          style={{
            padding: '40px 24px',
            background: 'var(--bg-card, #111827)',
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            textAlign: 'center',
          }}
        >
          <p
            style={{
              fontFamily: F.ui,
              fontSize: 13,
              color: 'var(--text-secondary, #94a3b8)',
              margin: 0,
              lineHeight: 1.6,
            }}
          >
            No campaigns configured. See{' '}
            <code
              style={{
                fontFamily: F.mono,
                fontSize: 12,
                color: 'var(--text-primary, #f1f5f9)',
                background: 'rgba(255,255,255,0.06)',
                padding: '1px 5px',
                borderRadius: 4,
              }}
            >
              apps/api/src/services/campaign_configs.py
            </code>
          </p>
        </div>
      )}
    </div>
  );
}
