import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Edit3,
  Filter,
  Layers,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Shield,
  SkipForward,
  Sparkles,
  Trash2,
  Webhook,
  XCircle,
  Zap,
} from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';

// ── Constants ─────────────────────────────────────────────────────────────

const POLL_LIST_MS = 12000;
const POLL_RUNS_MS = 6000;
const CRON_PREVIEW_DEBOUNCE_MS = 350;

const TRIGGER_ICON = {
  cron: Clock,
  event: Zap,
  webhook: Webhook,
  manual: Play,
};

const STATUS_TONE = {
  success: { fg: C.acc, dim: C.accDim, Icon: CheckCircle2, label: 'success' },
  ok:      { fg: C.acc, dim: C.accDim, Icon: CheckCircle2, label: 'ok' },
  failed:  { fg: C.danger, dim: C.dangerDim, Icon: XCircle, label: 'failed' },
  error:   { fg: C.danger, dim: C.dangerDim, Icon: XCircle, label: 'error' },
  skipped: { fg: C.txtS, dim: 'rgba(148,163,184,0.12)', Icon: SkipForward, label: 'skipped' },
  running: { fg: C.info, dim: 'rgba(56,189,248,0.15)', Icon: Loader2, label: 'running' },
  warn:    { fg: C.warning, dim: C.warningDim, Icon: AlertTriangle, label: 'warn' },
  info:    { fg: C.info, dim: 'rgba(56,189,248,0.15)', Icon: Bell, label: 'info' },
};

const EVENT_TYPES = [
  { key: 'evolution_started',   label: 'Evolution started'    },
  { key: 'champion_promoted',   label: 'Champion promoted'    },
  { key: 'generation_complete', label: 'Generation discarded' },
  { key: 'evolution_complete',  label: 'Evolution complete'   },
  { key: 'evolution_failed',    label: 'Evolution failed'     },
  { key: 'track_promoted',      label: 'Track promoted'       },
  { key: 'drift_detected',      label: 'Drift detected'       },
  { key: 'daily_report',        label: 'Daily report'         },
  { key: 'health_check',        label: 'Health check (noisy)' },
  { key: 'auto_cleanup',        label: 'Auto cleanup'         },
];

// ── Helpers ───────────────────────────────────────────────────────────────

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
  return STATUS_TONE[s] || STATUS_TONE.info;
}

function pillStyle(tone) {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '2px 8px', borderRadius: 999,
    background: tone.dim, color: tone.fg,
    fontFamily: F.mono, fontSize: 10, letterSpacing: '0.04em',
    border: `1px solid ${tone.fg}33`,
  };
}

function btn({ kind = 'default', disabled = false } = {}) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    padding: '6px 11px', fontFamily: F.ui, fontSize: 11.5, fontWeight: 600,
    border: `1px solid ${C.border}`, borderRadius: 6,
    background: 'transparent', color: C.txtS, cursor: disabled ? 'not-allowed' : 'pointer',
    transition: 'border-color 120ms, color 120ms, background 120ms',
    opacity: disabled ? 0.55 : 1,
  };
  if (kind === 'primary') return { ...base, background: C.acc, color: '#0a0e16', border: 'none' };
  if (kind === 'danger')  return { ...base, color: C.danger, borderColor: `${C.danger}55` };
  if (kind === 'ghost')   return { ...base, padding: '4px 8px', fontSize: 11 };
  return base;
}

function input(extras = {}) {
  return {
    width: '100%', background: C.bgI, border: `1px solid ${C.border}`,
    borderRadius: 6, color: C.txtP, padding: '7px 10px',
    fontFamily: F.mono, fontSize: 12, outline: 'none',
    ...extras,
  };
}

function label(extras = {}) {
  return {
    fontFamily: F.mono, fontSize: 10,
    color: C.txtM, letterSpacing: '0.06em',
    textTransform: 'uppercase', marginBottom: 4, ...extras,
  };
}

function sectionHeader(text, Icon) {
  return (
    <span style={{
      fontFamily: F.ui, fontSize: 12, fontWeight: 700,
      letterSpacing: '0.08em', textTransform: 'uppercase',
      color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 8,
    }}>
      {Icon ? <Icon size={13} /> : null}{text}
    </span>
  );
}

function emptyDraft() {
  return {
    id: null,
    name: 'New workflow',
    description: '',
    enabled: true,
    kind: 'user',
    trigger_type: 'cron',
    trigger_config: { cron: '0 2 * * *' },
    condition: null,
    actions: [],
    webhook_secret: null,
  };
}

// ── Cron builder ──────────────────────────────────────────────────────────

const CRON_PRESETS = [
  ['Every 15 minutes', '*/15 * * * *'],
  ['Every hour',        '0 * * * *'],
  ['Every 6 hours',     '0 */6 * * *'],
  ['Daily at 02:00',    '0 2 * * *'],
  ['Daily at 08:00',    '0 8 * * *'],
  ['Weekday at 09:00',  '0 9 * * 1-5'],
  ['Sunday at 09:00',   '0 9 * * 0'],
  ['Sunday at 03:00',   '0 3 * * 0'],
];

function CronBuilder({ value, onChange }) {
  const [preview, setPreview] = useState({ valid: true, fires: [], err: null });
  const tRef = useRef(null);

  useEffect(() => {
    if (tRef.current) clearTimeout(tRef.current);
    if (!value || !value.trim()) {
      setPreview({ valid: false, fires: [], err: 'empty' });
      return;
    }
    tRef.current = setTimeout(async () => {
      try {
        const r = await apiFetch(`/api/automation/cron/preview?expr=${encodeURIComponent(value)}`);
        setPreview({ valid: true, fires: r?.next_fires || [], err: null });
      } catch (e) {
        setPreview({ valid: false, fires: [], err: e?.message || 'invalid cron' });
      }
    }, CRON_PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(tRef.current);
  }, [value]);

  return (
    <div>
      <div style={label()}>Cron expression</div>
      <input
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0 2 * * *"
        style={input({ borderColor: preview.valid ? C.border : `${C.danger}55` })}
      />
      <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {CRON_PRESETS.map(([lbl, expr]) => (
          <button
            key={expr} type="button" onClick={() => onChange(expr)}
            style={{
              padding: '3px 8px', fontFamily: F.ui, fontSize: 10,
              background: expr === value ? C.accDim : 'transparent',
              border: `1px solid ${expr === value ? C.borderA : C.border}`,
              borderRadius: 999, color: expr === value ? C.acc : C.txtS, cursor: 'pointer',
            }}
          >
            {lbl}
          </button>
        ))}
      </div>
      <div style={{ marginTop: 8, fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
        {preview.valid && preview.fires.length > 0 ? (
          <>NEXT 5 FIRES (UTC):<br />
            {preview.fires.map((f) => (
              <div key={f} style={{ color: C.txtS }}>· {f.replace('T', ' ').slice(0, 19)}</div>
            ))}
          </>
        ) : preview.err === 'empty' ? null : (
          <span style={{ color: C.danger }}>{preview.err || 'invalid'}</span>
        )}
      </div>
    </div>
  );
}

// ── Action chain ──────────────────────────────────────────────────────────

function renderField(field, value, onChange) {
  const k = field.type || 'string';
  const v = value === undefined ? field.default ?? '' : value;
  if (k === 'textarea') {
    return (
      <textarea
        value={v ?? ''}
        rows={field.name === 'message' ? 3 : 4}
        onChange={(e) => onChange(e.target.value)}
        style={input({ minHeight: 60, resize: 'vertical', fontSize: 11.5 })}
      />
    );
  }
  if (k === 'number') {
    return (
      <input
        type="number"
        value={v === '' || v === null || v === undefined ? '' : v}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === '' ? null : Number(raw));
        }}
        style={input()}
      />
    );
  }
  if (k === 'boolean') {
    return (
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.ui, fontSize: 12, color: C.txtS, cursor: 'pointer' }}>
        <input type="checkbox" checked={!!v} onChange={(e) => onChange(e.target.checked)} style={{ accentColor: C.acc }} />
        {field.label}
      </label>
    );
  }
  if (k === 'select') {
    return (
      <select value={v ?? ''} onChange={(e) => onChange(e.target.value)} style={input()}>
        {(field.options || []).map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label || opt.value}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      type={field.name === 'webhook_secret' ? 'password' : 'text'}
      value={v ?? ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.placeholder || ''}
      style={input()}
    />
  );
}

function ActionStep({ index, total, action, schemaByKind, onChange, onMove, onRemove, onDuplicate }) {
  const cls = schemaByKind[action.kind];
  const fields = cls?.schema || [];
  const Icon = action.kind?.startsWith('notify') ? Send
    : action.kind?.startsWith('evolution') ? Sparkles
    : action.kind?.startsWith('ept') ? Layers
    : action.kind?.startsWith('cleanup') ? Trash2
    : action.kind?.startsWith('http') ? Webhook
    : action.kind?.startsWith('drift') ? AlertTriangle
    : action.kind?.startsWith('health') ? Shield
    : action.kind === 'wait' ? Pause
    : Bot;
  return (
    <div style={{
      background: C.bgI, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: 12, position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <div style={{
          width: 24, height: 24, borderRadius: 6,
          background: C.bgC, border: `1px solid ${C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: F.mono, fontSize: 10, color: C.txtS,
        }}>{index + 1}</div>
        <Icon size={14} color={C.txtS} />
        <select
          value={action.kind || ''}
          onChange={(e) => onChange({ ...action, kind: e.target.value, config: {} })}
          style={{ ...input({ width: 'auto', flex: 1, fontSize: 12 }) }}
        >
          <option value="" disabled>— pick an action —</option>
          {Object.values(schemaByKind).map((c) => (
            <option key={c.kind} value={c.kind}>{c.label}</option>
          ))}
        </select>
        <div style={{ display: 'flex', gap: 2 }}>
          <button type="button" disabled={index === 0} onClick={() => onMove(index, index - 1)}
                  title="Move up" style={btn({ kind: 'ghost', disabled: index === 0 })}>↑</button>
          <button type="button" disabled={index === total - 1} onClick={() => onMove(index, index + 1)}
                  title="Move down" style={btn({ kind: 'ghost', disabled: index === total - 1 })}>↓</button>
          <button type="button" onClick={() => onDuplicate(index)} title="Duplicate"
                  style={btn({ kind: 'ghost' })}><Copy size={11} /></button>
          <button type="button" onClick={() => onRemove(index)} title="Remove"
                  style={btn({ kind: 'ghost' })}><Trash2 size={11} color={C.danger} /></button>
        </div>
      </div>
      {cls?.description ? (
        <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, marginBottom: 10 }}>
          {cls.description}
        </div>
      ) : null}
      {fields.length === 0 ? (
        <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, fontStyle: 'italic' }}>
          (no configuration)
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {fields.map((f) => (
            <div key={f.name}>
              <div style={label()}>
                {f.label || f.name}
                {f.required ? <span style={{ color: C.danger, marginLeft: 4 }}>*</span> : null}
              </div>
              {renderField(f, action.config?.[f.name], (val) => onChange({
                ...action, config: { ...(action.config || {}), [f.name]: val },
              }))}
              {f.help ? (
                <div style={{ fontFamily: F.ui, fontSize: 10.5, color: C.txtM, marginTop: 3 }}>
                  {f.help}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Condition editor ──────────────────────────────────────────────────────

const CONDITION_OPS = ['==', '!=', '<', '<=', '>', '>=', 'contains', 'in'];

function ConditionEditor({ value, onChange }) {
  // Detect mode from current value:
  //   null/{}             → 'none'
  //   { <op>: [{var:..},lit] } → 'simple'
  //   else                → 'advanced'
  const detect = (cond) => {
    if (cond == null || (typeof cond === 'object' && Object.keys(cond).length === 0)) return 'none';
    if (typeof cond === 'object') {
      const keys = Object.keys(cond);
      if (keys.length === 1 && CONDITION_OPS.includes(keys[0])) {
        const args = cond[keys[0]];
        if (Array.isArray(args) && args.length === 2 && args[0] && args[0].var !== undefined) {
          return 'simple';
        }
      }
    }
    return 'advanced';
  };
  const [mode, setMode] = useState(() => detect(value));
  const [advancedText, setAdvancedText] = useState(() =>
    value ? JSON.stringify(value, null, 2) : '');

  useEffect(() => {
    const next = detect(value);
    if (next !== 'advanced') setAdvancedText(value ? JSON.stringify(value, null, 2) : '');
  }, [value]);

  const setMode_ = (m) => {
    setMode(m);
    if (m === 'none') onChange(null);
    if (m === 'simple' && (!value || detect(value) !== 'simple')) {
      onChange({ '==': [{ var: 'last.status' }, 'ok'] });
    }
  };

  // Pull the parts out for the simple editor.
  const simple = (() => {
    if (mode !== 'simple' || !value) return { op: '==', path: '', literal: '' };
    const op = Object.keys(value)[0];
    const args = value[op];
    return { op, path: args[0]?.var || '', literal: args[1] };
  })();

  return (
    <div style={{ background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        {sectionHeader('Condition', Filter)}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {['none', 'simple', 'advanced'].map((m) => (
            <button key={m} type="button" onClick={() => setMode_(m)}
                    style={{
                      padding: '3px 10px', fontFamily: F.ui, fontSize: 11,
                      borderRadius: 999, cursor: 'pointer',
                      background: mode === m ? C.accDim : 'transparent',
                      border: `1px solid ${mode === m ? C.borderA : C.border}`,
                      color: mode === m ? C.acc : C.txtS,
                      textTransform: 'capitalize',
                    }}>{m}</button>
          ))}
        </div>
      </div>
      {mode === 'none' ? (
        <div style={{ fontFamily: F.ui, fontSize: 11.5, color: C.txtM }}>
          Always run when triggered.
        </div>
      ) : mode === 'simple' ? (
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 90px 2fr', gap: 6 }}>
          <input
            value={simple.path}
            onChange={(e) => onChange({ [simple.op]: [{ var: e.target.value }, simple.literal] })}
            placeholder="last.drifts.0.delta_pct"
            style={input()}
          />
          <select
            value={simple.op}
            onChange={(e) => onChange({ [e.target.value]: [{ var: simple.path }, simple.literal] })}
            style={input()}
          >
            {CONDITION_OPS.map((op) => <option key={op} value={op}>{op}</option>)}
          </select>
          <input
            value={typeof simple.literal === 'object' ? JSON.stringify(simple.literal) : simple.literal ?? ''}
            onChange={(e) => {
              const raw = e.target.value;
              const numeric = raw !== '' && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
              onChange({ [simple.op]: [{ var: simple.path }, numeric] });
            }}
            placeholder="-5"
            style={input()}
          />
        </div>
      ) : (
        <textarea
          rows={6}
          value={advancedText}
          onChange={(e) => {
            setAdvancedText(e.target.value);
            try { onChange(JSON.parse(e.target.value)); } catch { /* ignore until parses */ }
          }}
          placeholder='{"and": [{">": [{"var":"child_avg"}, 0.6]}, {"==": [{"var":"promoted"}, true]}]}'
          style={input({ minHeight: 110, resize: 'vertical' })}
        />
      )}
      <div style={{ marginTop: 8, fontFamily: F.ui, fontSize: 10.5, color: C.txtM, lineHeight: 1.5 }}>
        Variables: trigger payload + <code style={{ color: C.acc }}>{'{last.<output>}'}</code>
        {' '}(previous action's output) + <code style={{ color: C.acc }}>{'{<action.kind>.<key>}'}</code>.
      </div>
    </div>
  );
}

// ── Workflow editor (center column) ───────────────────────────────────────

function WorkflowEditor({ workflow, onChange, onSave, onDelete, onTrigger, schemaByKind, triggerSchemas, dirty, busy }) {
  if (!workflow) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 10,
        color: C.txtM, fontFamily: F.ui,
      }}>
        <Bot size={32} color={C.txtM} />
        <div>Select a workflow on the left, or click <strong>+ New</strong>.</div>
      </div>
    );
  }
  const isSystem = workflow.kind === 'system';
  const triggerKind = workflow.trigger_type;
  const triggerSchema = triggerSchemas.find((t) => t.kind === triggerKind);

  const updateTriggerCfg = (next) => onChange({ ...workflow, trigger_config: { ...(workflow.trigger_config || {}), ...next } });

  const moveAction = (from, to) => {
    const arr = [...workflow.actions];
    const [a] = arr.splice(from, 1);
    arr.splice(to, 0, a);
    onChange({ ...workflow, actions: arr });
  };
  const removeAction = (i) => {
    const arr = [...workflow.actions];
    arr.splice(i, 1);
    onChange({ ...workflow, actions: arr });
  };
  const dupAction = (i) => {
    const arr = [...workflow.actions];
    arr.splice(i + 1, 0, JSON.parse(JSON.stringify(arr[i])));
    onChange({ ...workflow, actions: arr });
  };
  const updateAction = (i, next) => {
    const arr = [...workflow.actions];
    arr[i] = next;
    onChange({ ...workflow, actions: arr });
  };
  const addAction = () => {
    const firstKind = Object.keys(schemaByKind)[0] || 'notify.slack';
    const def = (schemaByKind[firstKind]?.schema || []).reduce((acc, f) => {
      if (f.default !== undefined) acc[f.name] = f.default;
      return acc;
    }, {});
    onChange({ ...workflow, actions: [...workflow.actions, { kind: firstKind, config: def }] });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: '100%', overflowY: 'auto', paddingRight: 4 }}>
      {/* Header */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <input
              value={workflow.name}
              disabled={isSystem}
              onChange={(e) => onChange({ ...workflow, name: e.target.value })}
              style={{
                ...input({ fontFamily: F.display, fontSize: 22, padding: '4px 0',
                          background: 'transparent', border: 'none', color: C.txtP }),
              }}
            />
            <input
              value={workflow.description || ''}
              onChange={(e) => onChange({ ...workflow, description: e.target.value })}
              placeholder="Short description (optional)"
              style={{
                ...input({ fontFamily: F.ui, fontSize: 12.5, padding: '2px 0',
                          background: 'transparent', border: 'none', color: C.txtS }),
              }}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {isSystem ? <span style={{ ...pillStyle(STATUS_TONE.info), background: 'rgba(129,140,248,0.12)', color: C.ind, borderColor: `${C.ind}55` }}>system</span> : null}
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <span style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS }}>Enabled</span>
              <input
                type="checkbox"
                checked={!!workflow.enabled}
                onChange={(e) => onChange({ ...workflow, enabled: e.target.checked })}
                style={{ accentColor: C.acc, width: 16, height: 16 }}
              />
            </label>
          </div>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" onClick={onSave} disabled={!dirty || busy}
                  style={btn({ kind: 'primary', disabled: !dirty || busy })}>
            <Save size={12} /> {workflow.id ? 'Save changes' : 'Create workflow'}
          </button>
          {workflow.id ? (
            <button type="button" onClick={onTrigger} disabled={busy}
                    style={btn({ disabled: busy })}>
              <Play size={12} /> Run now
            </button>
          ) : null}
          {workflow.id && !isSystem ? (
            <button type="button" onClick={onDelete} disabled={busy}
                    style={btn({ kind: 'danger', disabled: busy })}>
              <Trash2 size={12} /> Delete
            </button>
          ) : null}
        </div>
      </div>

      {/* Trigger picker */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ marginBottom: 10 }}>{sectionHeader('Trigger', Zap)}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6, marginBottom: 12 }}>
          {triggerSchemas.map((t) => {
            const Icon = TRIGGER_ICON[t.kind] || Zap;
            const active = workflow.trigger_type === t.kind;
            return (
              <button
                key={t.kind} type="button"
                onClick={() => onChange({ ...workflow, trigger_type: t.kind, trigger_config: {} })}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 3,
                  padding: '8px 10px', borderRadius: 7, cursor: 'pointer',
                  background: active ? C.accDim : C.bgI,
                  border: `1px solid ${active ? C.borderA : C.border}`,
                  color: active ? C.acc : C.txtS,
                  textAlign: 'left',
                }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.ui, fontSize: 12, fontWeight: 600 }}>
                  <Icon size={13} /> {t.label}
                </span>
                <span style={{ fontFamily: F.ui, fontSize: 10.5, color: active ? C.acc : C.txtM }}>
                  {t.description}
                </span>
              </button>
            );
          })}
        </div>
        {triggerKind === 'cron' ? (
          <CronBuilder value={workflow.trigger_config?.cron || ''} onChange={(v) => updateTriggerCfg({ cron: v })} />
        ) : null}
        {triggerKind === 'event' ? (
          <div>
            <div style={label()}>Event pattern (shell-style wildcards: <code>evolution.*</code>)</div>
            <input
              value={workflow.trigger_config?.pattern || ''}
              onChange={(e) => updateTriggerCfg({ pattern: e.target.value })}
              placeholder="champion.promoted"
              style={input()}
              list="known-events"
            />
            <datalist id="known-events">
              {(triggerSchema?.events || []).map((ev) => (
                <option key={ev.key} value={ev.key}>{ev.label}</option>
              ))}
            </datalist>
            <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {(triggerSchema?.events || []).map((ev) => (
                <button key={ev.key} type="button" onClick={() => updateTriggerCfg({ pattern: ev.key })}
                        style={{
                          padding: '3px 8px', fontFamily: F.mono, fontSize: 10,
                          background: ev.key === workflow.trigger_config?.pattern ? C.accDim : 'transparent',
                          border: `1px solid ${ev.key === workflow.trigger_config?.pattern ? C.borderA : C.border}`,
                          borderRadius: 999, color: ev.key === workflow.trigger_config?.pattern ? C.acc : C.txtS, cursor: 'pointer',
                        }}>
                  {ev.key}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {triggerKind === 'webhook' ? (
          <div>
            <div style={label()}>Webhook endpoint</div>
            {workflow.id ? (
              <code style={{ display: 'block', padding: '8px 10px', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, fontFamily: F.mono, fontSize: 11, color: C.acc, wordBreak: 'break-all' }}>
                POST /api/automation/hooks/{workflow.id}?secret={workflow.webhook_secret || '<saved-on-create>'}
              </code>
            ) : (
              <div style={{ fontFamily: F.ui, fontSize: 11.5, color: C.txtM }}>
                Save the workflow first — the URL + secret will be generated.
              </div>
            )}
          </div>
        ) : null}
        {triggerKind === 'manual' ? (
          <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM }}>
            Fires only when you click <strong>Run now</strong>.
          </div>
        ) : null}
      </div>

      {/* Condition */}
      <ConditionEditor value={workflow.condition} onChange={(c) => onChange({ ...workflow, condition: c })} />

      {/* Actions */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
          {sectionHeader('Actions', Sparkles)}
          <button type="button" onClick={addAction} style={{ ...btn(), marginLeft: 'auto' }}>
            <Plus size={12} /> Add action
          </button>
        </div>
        {workflow.actions.length === 0 ? (
          <div style={{ padding: 18, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 12, border: `1px dashed ${C.border}`, borderRadius: 8 }}>
            No actions yet — click <strong>+ Add action</strong>.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {workflow.actions.map((a, i) => (
              <ActionStep
                key={i}
                index={i} total={workflow.actions.length}
                action={a}
                schemaByKind={schemaByKind}
                onChange={(next) => updateAction(i, next)}
                onMove={moveAction}
                onRemove={removeAction}
                onDuplicate={dupAction}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Run history (right column) ────────────────────────────────────────────

function RunRow({ run }) {
  const [open, setOpen] = useState(false);
  const tone = statusTone(run.status);
  const Icon = tone.Icon;
  const dur = run.duration_ms != null
    ? (run.duration_ms < 1000 ? `${run.duration_ms}ms` : `${(run.duration_ms / 1000).toFixed(1)}s`)
    : '–';
  return (
    <div style={{ borderBottom: `1px solid ${C.border}` }}>
      <button type="button" onClick={() => setOpen(!open)} style={{
        width: '100%', textAlign: 'left', background: 'transparent', border: 'none',
        padding: '8px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {open ? <ChevronDown size={11} color={C.txtM} /> : <ChevronRight size={11} color={C.txtM} />}
        <Icon size={11} color={tone.fg} />
        <span style={{ fontFamily: F.mono, fontSize: 10.5, color: tone.fg, textTransform: 'uppercase' }}>{run.status}</span>
        <span style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS }}>· {run.trigger_kind}</span>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginLeft: 'auto' }}>{fmtAgo(run.started_at)} · {dur}</span>
      </button>
      {open ? (
        <div style={{ padding: '0 12px 12px 28px' }}>
          {run.error ? (
            <div style={{ marginBottom: 8, padding: 8, background: C.dangerDim, border: `1px solid ${C.danger}55`, borderRadius: 6, fontFamily: F.mono, fontSize: 11, color: C.danger, whiteSpace: 'pre-wrap' }}>
              {run.error}
            </div>
          ) : null}
          {run.condition_passed === false ? (
            <div style={{ marginBottom: 6, fontFamily: F.ui, fontSize: 11, color: C.txtM }}>
              Skipped — condition was false.
            </div>
          ) : null}
          {(run.step_traces || []).length === 0 ? (
            <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM }}>No steps executed.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(run.step_traces || []).map((s, idx) => {
                const t = statusTone(s.status);
                const SI = t.Icon;
                return (
                  <div key={idx} style={{ display: 'grid', gridTemplateColumns: '14px 1fr auto', gap: 6, alignItems: 'flex-start' }}>
                    <SI size={11} color={t.fg} style={{ marginTop: 2 }} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP }}>
                        {s.kind}
                        <span style={{ color: t.fg, marginLeft: 6, fontSize: 10 }}>· {s.status}</span>
                      </div>
                      <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS }}>{s.message}</div>
                      {s.error ? (
                        <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.danger, marginTop: 2, whiteSpace: 'pre-wrap' }}>
                          {s.error}
                        </div>
                      ) : null}
                      {s.output && Object.keys(s.output).length > 0 ? (
                        <details style={{ marginTop: 3 }}>
                          <summary style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, cursor: 'pointer' }}>output</summary>
                          <pre style={{ fontFamily: F.mono, fontSize: 10, color: C.txtS, background: C.bgI, padding: 6, borderRadius: 4, overflowX: 'auto', marginTop: 3 }}>
                            {JSON.stringify(s.output, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                    <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{s.duration_ms}ms</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function RunHistoryPanel({ workflow, runs, loading, onRefresh }) {
  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center' }}>
        {sectionHeader(workflow ? 'This workflow runs' : 'Recent runs (all)', Bell)}
        <button type="button" onClick={onRefresh} style={{ ...btn({ kind: 'ghost' }), marginLeft: 'auto' }}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {loading && runs.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 12 }}>
            Loading…
          </div>
        ) : runs.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 12 }}>
            No runs yet. Hit "Run now" or wait for the next trigger.
          </div>
        ) : runs.map((r) => <RunRow key={r.id} run={r} />)}
      </div>
    </div>
  );
}

// ── Slack + Settings (kept) ───────────────────────────────────────────────

function SlackPanel({ settings, onSave, onTest }) {
  const [url, setUrl] = useState('');
  const allowed = useMemo(() => new Set(settings?.notify_event_types || []), [settings]);
  const slackConfigured = Boolean(settings?.slack_webhook_url_masked);
  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
      <div style={{ marginBottom: 12 }}>{sectionHeader('Slack channel', Send)}</div>
      <div style={label()}>WEBHOOK URL</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={settings?.slack_webhook_url_masked || 'https://hooks.slack.com/...'}
          type="password"
          style={input()}
        />
        <button type="button" onClick={() => { if (url.trim()) { onSave({ slack_webhook_url: url.trim() }); setUrl(''); } }}
                disabled={!url.trim()} style={btn({ kind: 'primary', disabled: !url.trim() })}>Save</button>
        <button type="button" onClick={onTest} disabled={!slackConfigured}
                style={btn({ disabled: !slackConfigured })}>Test</button>
      </div>
      <div style={{ fontFamily: F.mono, fontSize: 10, color: slackConfigured ? C.txtM : C.warning, marginTop: 4 }}>
        {slackConfigured ? `configured: ${settings.slack_webhook_url_masked}` : 'Not configured — falls back to SLACK_WEBHOOK_URL env if set.'}
      </div>
      <div style={{ marginTop: 12, ...label() }}>EVENT TYPES TO NOTIFY (LEGACY notify() FAN-OUT)</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
        {EVENT_TYPES.map((ev) => {
          const checked = allowed.has(ev.key);
          return (
            <label key={ev.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.ui, fontSize: 11.5, color: C.txtS, cursor: 'pointer' }}>
              <input
                type="checkbox" checked={checked} style={{ accentColor: C.acc }}
                onChange={() => {
                  const next = new Set(allowed);
                  if (next.has(ev.key)) next.delete(ev.key); else next.add(ev.key);
                  onSave({ notify_event_types: Array.from(next) });
                }}
              />
              {ev.label}
            </label>
          );
        })}
      </div>
      <div style={{ marginTop: 8, fontFamily: F.ui, fontSize: 10.5, color: C.txtM }}>
        Workflow notify.slack actions can override the event tag per-action; the allow-list still gates legacy notify() fan-out from the evolution loop.
      </div>
    </div>
  );
}

function GuardsPanel({ settings, onSave }) {
  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
      <div style={{ marginBottom: 12 }}>{sectionHeader('Guards', Shield)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 4 }}>
            <span>Regression threshold</span>
            <span style={{ color: C.acc }}>{(settings?.regression_threshold_pct ?? 3.0).toFixed(1)}%</span>
          </div>
          <input
            type="range" min={1} max={10} step={0.5}
            value={settings?.regression_threshold_pct ?? 3.0}
            onChange={(e) => onSave({ regression_threshold_pct: parseFloat(e.target.value) })}
            style={{ width: '100%', accentColor: C.acc }}
          />
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 4 }}>
            <span>Cleanup keep days</span>
            <span style={{ color: C.acc }}>{settings?.cleanup_keep_days ?? 7} days</span>
          </div>
          <input
            type="range" min={1} max={30}
            value={settings?.cleanup_keep_days ?? 7}
            onChange={(e) => onSave({ cleanup_keep_days: parseInt(e.target.value, 10) })}
            style={{ width: '100%', accentColor: C.acc }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Workflow list (left rail) ─────────────────────────────────────────────

function WorkflowListItem({ wf, selected, onPick }) {
  const TriggerIcon = TRIGGER_ICON[wf.trigger_type] || Zap;
  const tone = statusTone(wf.last_run_status);
  const Last = tone.Icon;
  const summary = wf.trigger_type === 'cron' ? wf.trigger_config?.cron
    : wf.trigger_type === 'event' ? wf.trigger_config?.pattern
    : wf.trigger_type === 'webhook' ? 'POST /hooks/...'
    : 'manual';
  return (
    <button
      type="button" onClick={() => onPick(wf)}
      style={{
        width: '100%', textAlign: 'left', cursor: 'pointer',
        background: selected ? C.bgE : 'transparent',
        border: 'none', borderLeft: `3px solid ${selected ? C.acc : 'transparent'}`,
        padding: '10px 12px',
        display: 'flex', flexDirection: 'column', gap: 4,
        opacity: wf.enabled ? 1 : 0.55,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <TriggerIcon size={12} color={selected ? C.acc : C.txtS} />
        <span style={{ fontFamily: F.ui, fontSize: 12.5, fontWeight: 600, color: selected ? C.txtP : C.txtP, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {wf.name}
        </span>
        {wf.kind === 'system'
          ? <span style={{ fontFamily: F.mono, fontSize: 9, color: C.ind, padding: '1px 5px', borderRadius: 999, background: 'rgba(129,140,248,0.12)', border: `1px solid ${C.ind}55` }}>SYS</span>
          : null}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 10, color: C.txtM, minWidth: 0 }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{summary}</span>
        {wf.last_run_at ? (
          <>
            <Last size={10} color={tone.fg} />
            <span style={{ color: tone.fg }}>{fmtAgo(wf.last_run_at)}</span>
          </>
        ) : null}
      </div>
    </button>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function AutomationPage() {
  const [workflows, setWorkflows] = useState([]);
  const [actionSchemas, setActionSchemas] = useState({});
  const [triggerSchemas, setTriggerSchemas] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [originalDraft, setOriginalDraft] = useState(null);
  const [runs, setRuns] = useState([]);
  const [globalRuns, setGlobalRuns] = useState([]);
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('all');
  const [toast, setToast] = useState(null);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // ── Loaders ────────────────────────────────────────────────────────────
  const loadWorkflows = useCallback(async () => {
    try {
      const r = await apiFetch('/api/automation/workflows');
      setWorkflows(r?.workflows || []);
    } catch { setWorkflows([]); }
  }, []);
  const loadSchemas = useCallback(async () => {
    try {
      const [a, t] = await Promise.all([
        apiFetch('/api/automation/actions/schema'),
        apiFetch('/api/automation/triggers/schema'),
      ]);
      const map = {};
      (a?.actions || []).forEach((c) => { map[c.kind] = c; });
      setActionSchemas(map);
      setTriggerSchemas(t?.triggers || []);
    } catch { /* ignore */ }
  }, []);
  const loadSettings = useCallback(async () => {
    try { setSettings(await apiFetch('/api/automation/settings')); }
    catch { setSettings({}); }
  }, []);
  const loadRunsForSelected = useCallback(async () => {
    if (!selectedId) {
      setRuns([]); return;
    }
    setLoadingRuns(true);
    try {
      const r = await apiFetch(`/api/automation/workflows/${selectedId}/runs?limit=25`);
      setRuns(r?.runs || []);
    } catch { setRuns([]); }
    finally { setLoadingRuns(false); }
  }, [selectedId]);
  const loadGlobalRuns = useCallback(async () => {
    try {
      const r = await apiFetch('/api/automation/workflow_runs?limit=15');
      setGlobalRuns(r?.runs || []);
    } catch { setGlobalRuns([]); }
  }, []);

  useEffect(() => { loadWorkflows(); loadSchemas(); loadSettings(); loadGlobalRuns(); }, [loadWorkflows, loadSchemas, loadSettings, loadGlobalRuns]);
  useEffect(() => { const iv = setInterval(loadWorkflows, POLL_LIST_MS); return () => clearInterval(iv); }, [loadWorkflows]);
  useEffect(() => { const iv = setInterval(loadGlobalRuns, POLL_RUNS_MS); return () => clearInterval(iv); }, [loadGlobalRuns]);
  useEffect(() => { loadRunsForSelected(); const iv = setInterval(loadRunsForSelected, POLL_RUNS_MS); return () => clearInterval(iv); }, [loadRunsForSelected]);

  // ── Selection ─────────────────────────────────────────────────────────
  const pickWorkflow = (wf) => {
    setSelectedId(wf.id);
    setDraft(JSON.parse(JSON.stringify(wf)));
    setOriginalDraft(JSON.parse(JSON.stringify(wf)));
  };
  const startNew = () => {
    setSelectedId(null);
    const d = emptyDraft();
    setDraft(d);
    setOriginalDraft(JSON.parse(JSON.stringify(d)));
  };

  const dirty = useMemo(() =>
    JSON.stringify(draft) !== JSON.stringify(originalDraft),
    [draft, originalDraft]);

  // Push freshly loaded server data into the draft if user hasn't dirtied it.
  useEffect(() => {
    if (!selectedId) return;
    const fresh = workflows.find((w) => w.id === selectedId);
    if (fresh && originalDraft && !dirty) {
      setDraft(JSON.parse(JSON.stringify(fresh)));
      setOriginalDraft(JSON.parse(JSON.stringify(fresh)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflows, selectedId, dirty]);

  const showToast = (msg, tone = 'info') => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 3000);
  };

  // ── CRUD ───────────────────────────────────────────────────────────────
  async function saveDraft() {
    if (!draft) return;
    setBusy(true);
    try {
      const body = {
        name: draft.name, description: draft.description, enabled: draft.enabled,
        trigger_type: draft.trigger_type, trigger_config: draft.trigger_config,
        condition: draft.condition, actions: draft.actions,
      };
      let saved;
      if (draft.id) {
        saved = await apiFetch(`/api/automation/workflows/${draft.id}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        saved = await apiFetch('/api/automation/workflows', { method: 'POST', body: JSON.stringify(body) });
        setSelectedId(saved.id);
      }
      setDraft(JSON.parse(JSON.stringify(saved)));
      setOriginalDraft(JSON.parse(JSON.stringify(saved)));
      await loadWorkflows();
      showToast(draft.id ? 'Workflow saved' : 'Workflow created', 'success');
    } catch (e) {
      showToast(`Save failed: ${e?.message || 'unknown'}`, 'error');
    } finally { setBusy(false); }
  }
  async function deleteSelected() {
    if (!draft?.id) return;
    if (!window.confirm(`Delete "${draft.name}"?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/automation/workflows/${draft.id}`, { method: 'DELETE' });
      setDraft(null); setOriginalDraft(null); setSelectedId(null);
      await loadWorkflows();
      showToast('Workflow deleted', 'success');
    } catch (e) {
      showToast(`Delete failed: ${e?.message}`, 'error');
    } finally { setBusy(false); }
  }
  async function triggerSelected() {
    if (!draft?.id) return;
    setBusy(true);
    try {
      await apiFetch(`/api/automation/workflows/${draft.id}/trigger`, { method: 'POST', body: '{}' });
      showToast('Triggered — see runs panel for output', 'success');
      setTimeout(loadRunsForSelected, 700);
    } catch (e) {
      showToast(`Trigger failed: ${e?.message}`, 'error');
    } finally { setBusy(false); }
  }
  async function saveSettings(payload) {
    try {
      await apiFetch('/api/automation/settings', { method: 'PUT', body: JSON.stringify(payload) });
      await loadSettings();
    } catch (e) { showToast(`Save failed: ${e?.message}`, 'error'); }
  }
  async function testSlack() {
    try {
      await apiFetch('/api/automation/slack/test', { method: 'POST' });
      showToast('Test notification sent', 'success');
    } catch (e) { showToast(`Test failed: ${e?.message}`, 'error'); }
  }

  // ── Filtering ──────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    if (filter === 'all') return workflows;
    if (filter === 'system') return workflows.filter((w) => w.kind === 'system');
    if (filter === 'user') return workflows.filter((w) => w.kind === 'user');
    if (filter === 'active') return workflows.filter((w) => w.enabled);
    return workflows;
  }, [workflows, filter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '8px 0 40px', maxWidth: 1700, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Bot size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Automation</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Trigger → condition → actions. Cron, event, or webhook. Slack out today; Discord & email when we go production-ready.
          </p>
        </div>
      </div>

      {/* Three-column workspace */}
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr 380px', gap: 14, alignItems: 'stretch', minHeight: 'calc(100vh - 240px)' }}>
        {/* LEFT — workflow list */}
        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 6 }}>
            {sectionHeader('Workflows', Layers)}
            <button type="button" onClick={startNew} style={{ ...btn({ kind: 'primary' }), marginLeft: 'auto', padding: '4px 9px', fontSize: 11 }}>
              <Plus size={11} /> New
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4, padding: '8px 12px', borderBottom: `1px solid ${C.border}` }}>
            {[['all', 'All'], ['system', 'System'], ['user', 'User'], ['active', 'Active']].map(([k, lbl]) => (
              <button key={k} type="button" onClick={() => setFilter(k)} style={{
                padding: '3px 9px', fontFamily: F.ui, fontSize: 10.5,
                background: filter === k ? C.accDim : 'transparent',
                border: `1px solid ${filter === k ? C.borderA : C.border}`,
                color: filter === k ? C.acc : C.txtS,
                borderRadius: 999, cursor: 'pointer',
              }}>{lbl}</button>
            ))}
          </div>
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {filtered.length === 0 ? (
              <div style={{ padding: 16, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 12 }}>
                {workflows.length === 0 ? 'Engine seeds 7 default workflows on first boot — refresh in a moment.' : 'No workflows match the filter.'}
              </div>
            ) : (
              filtered.map((wf) => (
                <WorkflowListItem key={wf.id} wf={wf} selected={wf.id === selectedId} onPick={pickWorkflow} />
              ))
            )}
          </div>
        </div>

        {/* CENTER — editor */}
        <div style={{ minWidth: 0 }}>
          <WorkflowEditor
            workflow={draft}
            onChange={setDraft}
            onSave={saveDraft}
            onDelete={deleteSelected}
            onTrigger={triggerSelected}
            schemaByKind={actionSchemas}
            triggerSchemas={triggerSchemas}
            dirty={dirty}
            busy={busy}
          />
        </div>

        {/* RIGHT — run history */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <RunHistoryPanel
            workflow={draft?.id ? draft : null}
            runs={draft?.id ? runs : globalRuns}
            loading={draft?.id ? loadingRuns : false}
            onRefresh={draft?.id ? loadRunsForSelected : loadGlobalRuns}
          />
        </div>
      </div>

      {/* Settings row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 14 }}>
        <SlackPanel settings={settings} onSave={saveSettings} onTest={testSlack} />
        <GuardsPanel settings={settings} onSave={saveSettings} />
      </div>

      {toast ? (
        <div style={{
          position: 'fixed', bottom: 24, right: 24, padding: '10px 14px',
          background: toast.tone === 'error' ? `${C.danger}22` : toast.tone === 'success' ? `${C.acc}22` : C.bgC,
          border: `1px solid ${toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.border}`,
          color: toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.txtP,
          borderRadius: 6, fontFamily: F.ui, fontSize: 12, fontWeight: 600, zIndex: 200,
        }}>
          {toast.msg}
        </div>
      ) : null}
    </div>
  );
}
