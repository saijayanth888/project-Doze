import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Layers,
  RotateCcw,
  Server,
  Trash2,
  GitCompare,
} from 'lucide-react';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from 'recharts';
import { C, F } from '../config/colors';
import {
  compareAdapters,
  deleteAdapter,
  fetchAdapters,
  rollbackAdapter,
  serveAdapter,
} from '../config/api';

const MOCK = {
  adapters: [
    {
      adapter_id: 'run-demo__gen1',
      run_id: 'run-demo',
      generation: 1,
      base_model: 'llama3.2:3b',
      scores: { mmlu: 0.52, arc_challenge: 0.48, hellaswag: 0.61, gsm8k: 0.4, humaneval: 0.25 },
      size_mb: 120.5,
      is_champion: true,
      promoted: true,
      status: 'champion',
      weak_categories: ['gsm8k'],
      training_config: {},
    },
  ],
  total: 1,
  champion_id: 'run-demo__gen1',
  total_disk_mb: 120.5,
};

function avgScore(scores) {
  if (!scores || typeof scores !== 'object') return 0;
  const v = Object.values(scores);
  if (!v.length) return 0;
  return (v.reduce((a, b) => a + Number(b), 0) / v.length).toFixed(3);
}

export default function AdaptersPage() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [compareOpen, setCompareOpen] = useState(false);
  const [aId, setAId] = useState('');
  const [bId, setBId] = useState('');
  const [cmpPrompt, setCmpPrompt] = useState('Summarize the benefits of unit tests.');
  const [cmpResult, setCmpResult] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const d = await fetchAdapters();
      setData(d);
      setErr(null);
    } catch (e) {
      setData(MOCK);
      setErr('API unavailable — showing mock data');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows = data?.adapters || [];
  const radarData = useMemo(() => {
    if (!aId || !bId) return [];
    const ra = rows.find((r) => r.adapter_id === aId);
    const rb = rows.find((r) => r.adapter_id === bId);
    if (!ra?.scores || !rb?.scores) return [];
    const keys = new Set([...Object.keys(ra.scores), ...Object.keys(rb.scores)]);
    return Array.from(keys).map((k) => ({
      bench: k,
      a: Number(ra.scores[k] ?? 0),
      b: Number(rb.scores[k] ?? 0),
    }));
  }, [aId, bId, rows]);

  async function onServe(id) {
    setBusy(id + ':serve');
    try {
      await serveAdapter(id);
      await load();
    } catch {
      /* toast optional */
    } finally {
      setBusy('');
    }
  }

  async function onRollback(id) {
    if (!window.confirm(`Rollback champion to ${id}?`)) return;
    setBusy(id + ':rb');
    try {
      await rollbackAdapter(id);
      await load();
    } finally {
      setBusy('');
    }
  }

  async function onDelete(id) {
    if (!window.confirm(`Delete adapter ${id}? This cannot be undone.`)) return;
    setBusy(id + ':del');
    try {
      await deleteAdapter(id);
      await load();
    } finally {
      setBusy('');
    }
  }

  async function runCompare() {
    if (!aId || !bId) return;
    setBusy('compare');
    try {
      const r = await compareAdapters(aId, bId, cmpPrompt.trim() || undefined);
      setCmpResult(r);
    } catch {
      setCmpResult(null);
    } finally {
      setBusy('');
    }
  }

  return (
    <div style={{ padding: '8px 0 40px', maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <Layers size={22} color={C.acc} />
        <div>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Adapters</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            LoRA checkpoints, champion control, and Ollama serve targets
          </p>
        </div>
      </div>

      {err && (
        <div
          style={{
            padding: '10px 14px',
            background: C.warningDim,
            border: `1px solid ${C.warning}`,
            borderRadius: 8,
            color: C.warning,
            fontFamily: F.mono,
            fontSize: 12,
            marginBottom: 16,
          }}
        >
          {err}
        </div>
      )}

      <div
        className="mf-card-hover"
        style={{
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: 16,
          marginBottom: 16,
          display: 'flex',
          gap: 24,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ fontSize: 10, color: C.txtM, fontFamily: F.mono, letterSpacing: 1 }}>TOTAL ADAPTERS</div>
          <div style={{ fontFamily: F.mono, fontSize: 22, color: C.acc }}>{data?.total ?? 0}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: C.txtM, fontFamily: F.mono, letterSpacing: 1 }}>DISK (GB)</div>
          <div style={{ fontFamily: F.mono, fontSize: 22, color: C.txtS }}>
            {((data?.total_disk_mb || 0) / 1024).toFixed(2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: C.txtM, fontFamily: F.mono, letterSpacing: 1 }}>CHAMPION</div>
          <div style={{ fontFamily: F.mono, fontSize: 13, color: C.txtP }}>{data?.champion_id || '—'}</div>
        </div>
      </div>

      <div style={{ overflowX: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: C.bgC }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: F.ui, fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${C.border}`, color: C.txtM, textAlign: 'left' }}>
              <th style={{ padding: 12 }} />
              <th style={{ padding: 12 }}>Gen</th>
              <th style={{ padding: 12 }}>Run</th>
              <th style={{ padding: 12 }}>Avg</th>
              <th style={{ padding: 12 }}>Size MB</th>
              <th style={{ padding: 12 }}>Status</th>
              <th style={{ padding: 12 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Fragment key={row.adapter_id}>
                <tr style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: 8 }}>
                    <button
                      type="button"
                      onClick={() =>
                        setExpanded((e) => ({ ...e, [row.adapter_id]: !e[row.adapter_id] }))
                      }
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: C.txtS,
                        display: 'flex',
                        alignItems: 'center',
                      }}
                    >
                      {expanded[row.adapter_id] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </button>
                  </td>
                  <td style={{ padding: 12, fontFamily: F.mono, color: C.txtP }}>{row.generation}</td>
                  <td style={{ padding: 12, fontFamily: F.mono, color: C.txtS }}>{row.run_id}</td>
                  <td style={{ padding: 12, color: C.acc }}>{avgScore(row.scores)}</td>
                  <td style={{ padding: 12 }}>{Number(row.size_mb || 0).toFixed(1)}</td>
                  <td style={{ padding: 12 }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        background:
                          row.status === 'champion'
                            ? C.accDim
                            : row.promoted
                              ? C.successDim
                              : C.bgE,
                        color: row.status === 'champion' ? C.acc : C.txtS,
                      }}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td style={{ padding: 8 }}>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        title="Serve"
                        disabled={busy.startsWith(row.adapter_id)}
                        onClick={() => onServe(row.adapter_id)}
                        style={btnSmall()}
                      >
                        <Server size={13} /> Serve
                      </button>
                      <button
                        type="button"
                        title="Rollback"
                        disabled={busy.startsWith(row.adapter_id)}
                        onClick={() => onRollback(row.adapter_id)}
                        style={btnSmall()}
                      >
                        <RotateCcw size={13} />
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        disabled={row.is_champion || busy.startsWith(row.adapter_id)}
                        onClick={() => onDelete(row.adapter_id)}
                        style={{ ...btnSmall(), opacity: row.is_champion ? 0.4 : 1 }}
                      >
                        <Trash2 size={13} />
                      </button>
                      <button
                        type="button"
                        title="Compare"
                        onClick={() => {
                          setAId(row.adapter_id);
                          setCompareOpen(true);
                        }}
                        style={btnSmall()}
                      >
                        <GitCompare size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
                {expanded[row.adapter_id] && (
                  <tr>
                    <td colSpan={7} style={{ padding: '0 16px 16px 40px', background: C.bgS }}>
                      <div style={{ fontSize: 11, color: C.txtM, marginBottom: 8 }}>Per-benchmark</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                        {row.scores &&
                          Object.entries(row.scores).map(([k, v]) => (
                            <div
                              key={k}
                              style={{
                                padding: '6px 10px',
                                background: C.bgI,
                                borderRadius: 6,
                                border: `1px solid ${C.border}`,
                              }}
                            >
                              <span style={{ color: C.txtM }}>{k}</span>{' '}
                              <span style={{ fontFamily: F.mono, color: C.txtP }}>{Number(v).toFixed(3)}</span>
                            </div>
                          ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {compareOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.65)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div
            style={{
              background: C.bgC,
              border: `1px solid ${C.border}`,
              borderRadius: 12,
              padding: 24,
              maxWidth: 900,
              width: '100%',
              maxHeight: '90vh',
              overflow: 'auto',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ fontFamily: F.ui, fontWeight: 700, color: C.txtP }}>Compare adapters</div>
              <button type="button" onClick={() => setCompareOpen(false)} style={{ ...btnGhost() }}>
                Close
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              <select
                value={aId}
                onChange={(e) => setAId(e.target.value)}
                style={selectStyle()}
              >
                <option value="">Adapter A</option>
                {rows.map((r) => (
                  <option key={r.adapter_id} value={r.adapter_id}>
                    {r.adapter_id}
                  </option>
                ))}
              </select>
              <select value={bId} onChange={(e) => setBId(e.target.value)} style={selectStyle()}>
                <option value="">Adapter B</option>
                {rows.map((r) => (
                  <option key={r.adapter_id} value={r.adapter_id}>
                    {r.adapter_id}
                  </option>
                ))}
              </select>
            </div>
            <textarea
              value={cmpPrompt}
              onChange={(e) => setCmpPrompt(e.target.value)}
              rows={2}
              style={{
                width: '100%',
                marginBottom: 12,
                background: C.bgI,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                color: C.txtP,
                padding: 10,
                fontFamily: F.mono,
                fontSize: 12,
              }}
            />
            <button type="button" className="mf-cta-primary" onClick={runCompare} style={{ marginBottom: 16 }}>
              Run comparison
            </button>
            {radarData.length > 0 && (
              <div style={{ height: 280, marginBottom: 16 }}>
                <ResponsiveContainer>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke={C.border} />
                    <PolarAngleAxis dataKey="bench" tick={{ fill: C.txtM, fontSize: 10 }} />
                    <PolarRadiusAxis angle={30} domain={[0, 1]} tick={{ fill: C.txtM, fontSize: 9 }} />
                    <Radar name="A" dataKey="a" stroke={C.ind} fill={C.ind} fillOpacity={0.35} />
                    <Radar name="B" dataKey="b" stroke={C.acc} fill={C.acc} fillOpacity={0.25} />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            )}
            {cmpResult?.inference_a && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 12 }}>
                <div style={{ padding: 12, background: C.bgS, borderRadius: 8, color: C.txtS }}>
                  <strong style={{ color: C.ind }}>A</strong>
                  <p style={{ marginTop: 8 }}>{cmpResult.inference_a.response || '—'}</p>
                </div>
                <div style={{ padding: 12, background: C.bgS, borderRadius: 8, color: C.txtS }}>
                  <strong style={{ color: C.acc }}>B</strong>
                  <p style={{ marginTop: 8 }}>{cmpResult.inference_b?.response || '—'}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function btnSmall() {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '4px 8px',
    fontSize: 11,
    background: C.bgE,
    border: `1px solid ${C.border}`,
    borderRadius: 6,
    color: C.txtS,
    cursor: 'pointer',
    fontFamily: F.ui,
  };
}

function btnGhost() {
  return {
    background: 'none',
    border: `1px solid ${C.border}`,
    borderRadius: 6,
    color: C.txtS,
    cursor: 'pointer',
    padding: '6px 12px',
    fontFamily: F.ui,
    fontSize: 12,
  };
}

function selectStyle() {
  return {
    width: '100%',
    padding: '8px 10px',
    background: C.bgI,
    border: `1px solid ${C.border}`,
    borderRadius: 6,
    color: C.txtP,
    fontFamily: F.mono,
    fontSize: 12,
  };
}
