import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Brain,
  CheckCircle2,
  ChevronDown,
  Clock,
  Cpu,
  Pause,
  Play,
  RefreshCw,
  Send,
  Shield,
  Sparkles,
  Trash2,
  XCircle,
} from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';

const POLL_LOG_MS = 10000;
const POLL_JOBS_MS = 15000;

const EVENT_TYPES = [
  { key: 'evolution_started',   label: 'Evolution started',   default: true },
  { key: 'champion_promoted',   label: 'Champion promoted',   default: true },
  { key: 'generation_complete', label: 'Generation discarded',default: false },
  { key: 'evolution_complete',  label: 'Evolution complete',  default: true },
  { key: 'evolution_failed',    label: 'Evolution failed',    default: true },
  { key: 'drift_detected',      label: 'Drift detected',      default: true },
  { key: 'daily_report',        label: 'Daily report',        default: true },
  { key: 'health_check',        label: 'Health check (noisy)',default: false },
  { key: 'auto_cleanup',        label: 'Auto cleanup',        default: false },
];

const JOB_ICON = {
  evolution_scheduler: Sparkles,
  drift_detection:     AlertTriangle,
  health_check:        Cpu,
  daily_report:        Bell,
  weekly_summary:      Bell,
  auto_cleanup:        Trash2,
};

function fmtAgo(ts) {
  if (!ts) return 'never';
  const t = new Date(ts).getTime();
  if (!Number.isFinite(t)) return String(ts);
  const dt = (Date.now() - t) / 1000;
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return new Date(ts).toLocaleString();
}

function statusTone(s) {
  if (s === 'error') return { fg: C.danger, Icon: XCircle };
  if (s === 'warn')  return { fg: C.warning, Icon: AlertTriangle };
  return { fg: C.acc, Icon: CheckCircle2 };
}

function JobCard({ job, onToggle, onTrigger, onEdit, busy }) {
  const Icon = JOB_ICON[job.job_id] || Sparkles;
  const lastTone = statusTone(job.last_run_status);
  const Last = lastTone.Icon;
  return (
    <div
      style={{
        background: C.bgC,
        border: `1px solid ${job.enabled ? `${C.acc}55` : C.border}`,
        borderRadius: 8,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div
          style={{
            width: 32, height: 32, borderRadius: 8,
            background: job.enabled ? `${C.acc}1a` : 'rgba(255,255,255,0.04)',
            border: `1px solid ${job.enabled ? `${C.acc}55` : C.border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Icon size={16} color={job.enabled ? C.acc : C.txtM} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, fontWeight: 600 }}>
            {job.name}
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 2 }}>
            {job.cron_human || job.cron} · {job.cron}
          </div>
        </div>
        <button
          type="button"
          onClick={() => onToggle(job)}
          disabled={busy === job.job_id}
          title={job.enabled ? 'Disable' : 'Enable'}
          style={{
            width: 38, height: 22, borderRadius: 999,
            background: job.enabled ? C.acc : C.bgI,
            border: `1px solid ${job.enabled ? C.acc : C.border}`,
            cursor: busy === job.job_id ? 'wait' : 'pointer', position: 'relative',
            transition: 'background 200ms',
          }}
        >
          <span
            style={{
              position: 'absolute', top: 2, left: job.enabled ? 18 : 2,
              width: 16, height: 16, borderRadius: 999,
              background: '#0a0e16',
              transition: 'left 200ms',
            }}
            aria-hidden
          />
        </button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 11, color: C.txtM, minHeight: 16 }}>
        {job.last_run_at ? (
          <>
            <Last size={11} color={lastTone.fg} />
            <span style={{ color: lastTone.fg }}>{job.last_run_status || 'ok'}</span>
            <span>· {fmtAgo(job.last_run_at)}</span>
          </>
        ) : (
          <span>Never run</span>
        )}
      </div>
      {job.last_run_message ? (
        <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS, lineHeight: 1.4 }}>
          {String(job.last_run_message).slice(0, 180)}
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
        <button
          type="button"
          onClick={() => onTrigger(job)}
          disabled={busy === job.job_id}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', fontSize: 11, fontFamily: F.ui,
            background: 'transparent', border: `1px solid ${C.border}`,
            borderRadius: 6, color: C.txtS, cursor: busy === job.job_id ? 'wait' : 'pointer',
          }}
        >
          <Play size={11} /> Run now
        </button>
        <button
          type="button"
          onClick={() => onEdit(job)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '5px 10px', fontSize: 11, fontFamily: F.ui,
            background: 'transparent', border: `1px solid ${C.border}`,
            borderRadius: 6, color: C.txtS, cursor: 'pointer',
          }}
        >
          <ChevronDown size={11} /> Edit
        </button>
      </div>
    </div>
  );
}

function EditDialog({ job, onClose, onSave }) {
  const [cron, setCron] = useState(job.cron);
  const [config, setConfig] = useState(JSON.stringify(job.config || {}, null, 2));
  const [err, setErr] = useState(null);
  if (!job) return null;
  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: 520, background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20 }}
      >
        <div style={{ fontFamily: F.ui, fontSize: 14, fontWeight: 700, color: C.txtP, marginBottom: 12 }}>
          Edit {job.name}
        </div>
        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Cron</div>
          <input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="0 2 * * *"
            style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtP, padding: '8px 10px', fontFamily: F.mono, fontSize: 12 }}
          />
        </label>
        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Config (JSON)</div>
          <textarea
            value={config}
            onChange={(e) => setConfig(e.target.value)}
            rows={8}
            style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtP, padding: '8px 10px', fontFamily: F.mono, fontSize: 12, resize: 'vertical' }}
          />
        </label>
        {err ? <div style={{ color: C.danger, fontFamily: F.mono, fontSize: 11, marginBottom: 8 }}>{err}</div> : null}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose} style={{ padding: '6px 12px', fontFamily: F.ui, fontSize: 12, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtS, cursor: 'pointer' }}>Cancel</button>
          <button
            type="button"
            onClick={() => {
              let cfg;
              try { cfg = JSON.parse(config); }
              catch (e) { setErr('Config is not valid JSON'); return; }
              onSave({ cron: cron.trim(), config: cfg });
            }}
            style={{ padding: '6px 12px', fontFamily: F.ui, fontSize: 12, fontWeight: 600, background: C.acc, color: '#0a0e16', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AutomationPage() {
  const [jobs, setJobs] = useState([]);
  const [logEntries, setLogEntries] = useState([]);
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState('');
  const [editing, setEditing] = useState(null);
  const [slackUrl, setSlackUrl] = useState('');
  const [toast, setToast] = useState(null);

  const loadJobs = useCallback(async () => {
    try {
      const r = await apiFetch('/api/automation/jobs');
      setJobs(r?.jobs || []);
    } catch {
      setJobs([]);
    }
  }, []);
  const loadLog = useCallback(async () => {
    try {
      const r = await apiFetch('/api/automation/log?limit=50');
      setLogEntries(r?.entries || []);
    } catch {
      setLogEntries([]);
    }
  }, []);
  const loadSettings = useCallback(async () => {
    try {
      const r = await apiFetch('/api/automation/settings');
      setSettings(r);
    } catch {
      setSettings({});
    }
  }, []);

  useEffect(() => { loadJobs(); loadLog(); loadSettings(); }, [loadJobs, loadLog, loadSettings]);
  useEffect(() => { const iv = setInterval(loadJobs, POLL_JOBS_MS); return () => clearInterval(iv); }, [loadJobs]);
  useEffect(() => { const iv = setInterval(loadLog, POLL_LOG_MS); return () => clearInterval(iv); }, [loadLog]);

  const showToast = (msg, tone = 'info') => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 3000);
  };

  async function toggleJob(job) {
    setBusy(job.job_id);
    try {
      await apiFetch(`/api/automation/jobs/${job.job_id}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !job.enabled }),
      });
      await loadJobs();
      showToast(`${job.name} ${!job.enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (e) {
      showToast(`Toggle failed: ${e?.message}`, 'error');
    } finally {
      setBusy('');
    }
  }
  async function triggerJob(job) {
    setBusy(job.job_id);
    try {
      await apiFetch(`/api/automation/jobs/${job.job_id}/trigger`, { method: 'POST' });
      showToast(`${job.name} triggered — will appear in log shortly`, 'success');
      setTimeout(loadLog, 800);
    } catch (e) {
      showToast(`Trigger failed: ${e?.message}`, 'error');
    } finally {
      setBusy('');
    }
  }
  async function saveEdit(payload) {
    if (!editing) return;
    try {
      await apiFetch(`/api/automation/jobs/${editing.job_id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setEditing(null);
      await loadJobs();
      showToast(`${editing.name} updated`, 'success');
    } catch (e) {
      showToast(`Save failed: ${e?.message}`, 'error');
    }
  }
  async function clearLog() {
    if (!window.confirm('Clear the automation log?')) return;
    try {
      await apiFetch('/api/automation/log', { method: 'DELETE' });
      await loadLog();
    } catch {}
  }
  async function testSlack() {
    try {
      await apiFetch('/api/automation/slack/test', { method: 'POST' });
      showToast('Test notification sent', 'success');
    } catch (e) {
      showToast(`Test failed: ${e?.message}`, 'error');
    }
  }
  async function saveSlackUrl() {
    try {
      await apiFetch('/api/automation/settings', {
        method: 'PUT',
        body: JSON.stringify({ slack_webhook_url: slackUrl.trim() }),
      });
      setSlackUrl('');
      await loadSettings();
      showToast('Slack URL saved', 'success');
    } catch (e) {
      showToast(`Save failed: ${e?.message}`, 'error');
    }
  }
  async function toggleEvent(key) {
    const current = new Set(settings?.notify_event_types || []);
    if (current.has(key)) current.delete(key);
    else current.add(key);
    try {
      await apiFetch('/api/automation/settings', {
        method: 'PUT',
        body: JSON.stringify({ notify_event_types: Array.from(current) }),
      });
      await loadSettings();
    } catch (e) {
      showToast(`Save failed: ${e?.message}`, 'error');
    }
  }
  async function saveGuards(payload) {
    try {
      await apiFetch('/api/automation/settings', { method: 'PUT', body: JSON.stringify(payload) });
      await loadSettings();
      showToast('Guards updated', 'success');
    } catch (e) {
      showToast(`Save failed: ${e?.message}`, 'error');
    }
  }

  const allowed = useMemo(() => new Set(settings?.notify_event_types || []), [settings]);
  const slackConfigured = Boolean(settings?.slack_webhook_url_masked);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '8px 0 40px', maxWidth: 1500, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Brain size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Automation</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            In-process scheduler, Slack notifications, guards, and execution log — replaces n8n.
          </p>
        </div>
      </div>

      {/* Jobs grid */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Clock size={13} /> Scheduled jobs
          </span>
          <button
            type="button"
            onClick={loadJobs}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontFamily: F.ui, fontSize: 11, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtS, cursor: 'pointer' }}
          >
            <RefreshCw size={11} /> Refresh
          </button>
        </div>
        {jobs.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', fontFamily: F.ui, color: C.txtM, fontSize: 13 }}>
            No jobs registered yet. The engine seeds 6 defaults on first boot.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10 }}>
            {jobs.map((j) => (
              <JobCard
                key={j.job_id}
                job={j}
                busy={busy}
                onToggle={toggleJob}
                onTrigger={triggerJob}
                onEdit={setEditing}
              />
            ))}
          </div>
        )}
      </div>

      {/* Two-column: Slack + Guards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 14 }}>
        {/* Slack notifications panel */}
        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Send size={13} /> Slack notifications
          </span>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginBottom: 4 }}>WEBHOOK URL</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={slackUrl}
                onChange={(e) => setSlackUrl(e.target.value)}
                placeholder={settings?.slack_webhook_url_masked || 'https://hooks.slack.com/...'}
                type="password"
                style={{ flex: 1, background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtP, padding: '6px 10px', fontFamily: F.mono, fontSize: 12 }}
              />
              <button
                type="button"
                onClick={saveSlackUrl}
                disabled={!slackUrl.trim()}
                style={{ padding: '6px 10px', fontFamily: F.ui, fontSize: 11, background: slackUrl.trim() ? C.acc : C.bgI, color: slackUrl.trim() ? '#0a0e16' : C.txtM, border: 'none', borderRadius: 6, cursor: slackUrl.trim() ? 'pointer' : 'not-allowed', fontWeight: 600 }}
              >
                Save
              </button>
              <button
                type="button"
                onClick={testSlack}
                disabled={!slackConfigured}
                style={{ padding: '6px 10px', fontFamily: F.ui, fontSize: 11, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, color: slackConfigured ? C.txtS : C.txtM, cursor: slackConfigured ? 'pointer' : 'not-allowed' }}
              >
                Test
              </button>
            </div>
            {settings?.slack_webhook_url_masked ? (
              <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 4 }}>
                configured: {settings.slack_webhook_url_masked}
              </div>
            ) : (
              <div style={{ fontFamily: F.mono, fontSize: 10, color: C.warning, marginTop: 4 }}>
                Not configured — falls back to SLACK_WEBHOOK_URL env if set.
              </div>
            )}
          </div>

          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginBottom: 6 }}>EVENT TYPES TO NOTIFY</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {EVENT_TYPES.map((ev) => {
              const checked = allowed.has(ev.key);
              return (
                <label key={ev.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.ui, fontSize: 12, color: C.txtS, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleEvent(ev.key)}
                    style={{ accentColor: C.acc }}
                  />
                  {ev.label}
                  <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{ev.key}</span>
                </label>
              );
            })}
          </div>
        </div>

        {/* Guards panel */}
        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Shield size={13} /> Guards
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 4 }}>
                <span>Regression threshold</span>
                <span style={{ color: C.acc }}>{(settings?.regression_threshold_pct ?? 3.0).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min={1}
                max={10}
                step={0.5}
                value={settings?.regression_threshold_pct ?? 3.0}
                onChange={(e) => setSettings((s) => ({ ...(s || {}), regression_threshold_pct: parseFloat(e.target.value) }))}
                onMouseUp={(e) => saveGuards({ regression_threshold_pct: parseFloat(e.target.value) })}
                onTouchEnd={(e) => saveGuards({ regression_threshold_pct: parseFloat(e.target.value) })}
                style={{ width: '100%', accentColor: C.acc }}
              />
              <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, marginTop: 4 }}>
                Held-out + per-bench drop above this discards the gen even if avg improves.
              </div>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 4 }}>
                <span>Cleanup keep days</span>
                <span style={{ color: C.acc }}>{settings?.cleanup_keep_days ?? 7} days</span>
              </div>
              <input
                type="range"
                min={1}
                max={30}
                value={settings?.cleanup_keep_days ?? 7}
                onChange={(e) => setSettings((s) => ({ ...(s || {}), cleanup_keep_days: parseInt(e.target.value, 10) }))}
                onMouseUp={(e) => saveGuards({ cleanup_keep_days: parseInt(e.target.value, 10) })}
                onTouchEnd={(e) => saveGuards({ cleanup_keep_days: parseInt(e.target.value, 10) })}
                style={{ width: '100%', accentColor: C.acc }}
              />
              <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, marginTop: 4 }}>
                Auto-cleanup deletes discarded adapter dirs older than this many days. Champion lineage is never touched.
              </div>
            </div>
            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.ui, fontSize: 12, color: C.txtS, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={!!settings?.memory_guard_enabled}
                  onChange={(e) => saveGuards({ memory_guard_enabled: e.target.checked })}
                  style={{ accentColor: C.acc }}
                />
                Memory guard
              </label>
              {settings?.memory_guard_enabled ? (
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={settings?.memory_guard_max_gb ?? ''}
                  onChange={(e) => setSettings((s) => ({ ...(s || {}), memory_guard_max_gb: parseFloat(e.target.value) }))}
                  onBlur={(e) => saveGuards({ memory_guard_max_gb: parseFloat(e.target.value) })}
                  placeholder="Max GB"
                  style={{ marginTop: 6, width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtP, padding: '6px 10px', fontFamily: F.mono, fontSize: 12 }}
                />
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Execution log */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Bell size={13} /> Execution log
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={loadLog}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontFamily: F.ui, fontSize: 11, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtS, cursor: 'pointer' }}
            >
              <RefreshCw size={11} /> Refresh
            </button>
            <button
              type="button"
              onClick={clearLog}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontFamily: F.ui, fontSize: 11, background: 'transparent', border: `1px solid ${C.danger}55`, borderRadius: 6, color: C.danger, cursor: 'pointer' }}
            >
              <Trash2 size={11} /> Clear
            </button>
          </div>
        </div>
        <div style={{ maxHeight: 360, overflowY: 'auto' }}>
          {logEntries.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', fontFamily: F.ui, fontSize: 13, color: C.txtM }}>
              No entries yet. Toggle a job on or hit "Run now" to populate.
            </div>
          ) : (
            logEntries.map((e) => {
              const tone = statusTone(e.level);
              const Icon = tone.Icon;
              return (
                <div
                  key={e.id}
                  style={{ display: 'grid', gridTemplateColumns: '120px 18px 1fr', gap: 10, padding: '6px 16px', borderBottom: `1px solid rgba(30,41,59,0.5)`, alignItems: 'flex-start' }}
                >
                  <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{fmtAgo(e.created_at)}</span>
                  <Icon size={13} color={tone.fg} style={{ marginTop: 1 }} />
                  <div style={{ minWidth: 0 }}>
                    <span style={{ fontFamily: F.mono, fontSize: 11, color: tone.fg }}>{e.job_id}</span>
                    <span style={{ fontFamily: F.ui, fontSize: 11, color: C.txtP, marginLeft: 8 }}>{e.message}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {editing ? (
        <EditDialog
          job={editing}
          onClose={() => setEditing(null)}
          onSave={saveEdit}
        />
      ) : null}

      {toast ? (
        <div
          style={{
            position: 'fixed', bottom: 24, right: 24,
            padding: '10px 14px',
            background: toast.tone === 'error' ? `${C.danger}22` : toast.tone === 'success' ? `${C.acc}22` : C.bgC,
            border: `1px solid ${toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.border}`,
            color: toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.txtP,
            borderRadius: 6, fontFamily: F.ui, fontSize: 12, fontWeight: 600,
            zIndex: 200, animation: 'slide-up-fade 200ms ease-out',
          }}
        >
          {toast.msg}
        </div>
      ) : null}
    </div>
  );
}
