import { useCallback, useEffect, useRef, useState } from 'react';
import { Database, RefreshCw, Trash2, Upload } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { C, F } from '../config/colors';
import {
  deleteDataset,
  fetchDatasets,
  getDataset,
  getDatasetQuality,
  uploadDataset,
} from '../config/api';
import LoadingSkeleton from '../components/shared/LoadingSkeleton';

export default function DatasetsPage() {
  const [list, setList] = useState(null);
  const [warn, setWarn] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [preview, setPreview] = useState(null);
  const [quality, setQuality] = useState(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  // Track previous count so we can briefly highlight new datasets the curator
  // just dropped (during evolution runs, gen-N appears mid-flight).
  const prevCountRef = useRef(0);
  const [flashId, setFlashId] = useState(null);

  /**
   * @param {boolean} silent - true when triggered by the auto-refresh tick;
   *   suppresses the loading spinner so the list doesn't blink every poll.
   */
  const loadList = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const d = await fetchDatasets();
      setList(d);
      setWarn(null);
      setLastUpdated(Date.now());
      const incoming = d?.datasets || [];
      // Detect newly-arrived datasets (curated dirs the API hadn't seen on
      // the previous poll). Flash the latest one for ~3s.
      if (silent && incoming.length > prevCountRef.current) {
        const newest = [...incoming].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
        if (newest) {
          setFlashId(newest.dataset_id);
          setTimeout(() => setFlashId((curr) => (curr === newest.dataset_id ? null : curr)), 3000);
        }
      }
      prevCountRef.current = incoming.length;
    } catch (e) {
      if (!silent) setList({ datasets: [], total: 0 });
      const st = e?.status;
      if (!silent) setWarn(st === 401 || st === 403 ? 'API key not configured — check Settings.' : 'Could not load datasets — check API connectivity.');
    }
    if (!silent) setLoading(false);
  }, []);

  useEffect(() => {
    loadList(false);
  }, [loadList]);

  // Auto-refresh: poll every 5s while enabled. Cheap (single endpoint, ~50ms)
  // and immediately surfaces new curator outputs during evolution runs.
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const iv = setInterval(() => loadList(true), 5000);
    return () => clearInterval(iv);
  }, [autoRefresh, loadList]);

  // If a dataset is currently selected and its sample count changes (curator
  // appended rows), re-fetch its preview so the right-hand panel stays fresh.
  useEffect(() => {
    if (!selected || !list?.datasets) return;
    const sel = list.datasets.find((d) => d.dataset_id === selected);
    if (sel && preview && sel.num_samples !== preview.total) {
      // Best-effort re-fetch; ignored if the API doesn't return total.
      getDataset(selected).then(setPreview).catch(() => {});
    }
  }, [list, selected, preview]);

  async function openDataset(id) {
    setSelected(id);
    try {
      const p = await getDataset(id);
      setPreview(p);
    } catch {
      setPreview(null);
    }
    try {
      const q = await getDatasetQuality(id);
      setQuality(q);
    } catch {
      setQuality(null);
    }
  }

  async function onFile(f) {
    if (!f) return;
    setUploading(true);
    try {
      await uploadDataset(f);
      await loadList();
    } finally {
      setUploading(false);
    }
  }

  async function onDrop(e) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) await onFile(f);
  }

  const histData =
    quality?.length_histogram?.instruction_buckets?.map((n, i) => ({
      bucket: ['0-128', '128-512', '512-2k', '2k+'][i],
      n,
    })) || [];

  const ds = list?.datasets || [];

  return (
    <div style={{ padding: '8px 0 40px', maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <Database size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Datasets</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Curated evolution data and custom JSONL uploads
          </p>
        </div>
        {/* Live-refresh controls — saves the user from F5'ing during a run. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: autoRefresh ? C.acc : C.txtM,
              boxShadow: autoRefresh ? `0 0 8px ${C.acc}` : 'none',
              animation: autoRefresh ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
          <span title="Polls /api/datasets every 5s when enabled">
            {autoRefresh ? 'Live · ' : 'Paused · '}
            {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : '—'}
          </span>
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            style={{
              padding: '4px 10px',
              fontSize: 11,
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.txtS,
              cursor: 'pointer',
              fontFamily: F.ui,
            }}
          >
            {autoRefresh ? 'Pause' : 'Resume'}
          </button>
          <button
            type="button"
            onClick={() => loadList(false)}
            title="Refresh now"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 10px',
              fontSize: 11,
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.txtS,
              cursor: 'pointer',
              fontFamily: F.ui,
            }}
          >
            <RefreshCw size={11} />
            Refresh
          </button>
        </div>
      </div>

      {warn && (
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
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <span>{warn}</span>
            <button
              type="button"
              onClick={loadList}
              style={{
                padding: '6px 10px',
                borderRadius: 6,
                border: `1px solid ${C.border}`,
                background: C.bgE,
                color: C.txtS,
                cursor: 'pointer',
                fontFamily: F.ui,
                fontSize: 12,
                whiteSpace: 'nowrap',
              }}
            >
              Retry
            </button>
          </div>
        </div>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        style={{
          border: `2px dashed ${drag ? C.acc : C.border}`,
          borderRadius: 12,
          padding: 32,
          textAlign: 'center',
          marginBottom: 24,
          background: drag ? C.accDim : C.bgC,
          transition: 'border-color 150ms',
        }}
      >
        <Upload size={28} color={C.txtM} style={{ marginBottom: 8 }} />
        <div style={{ fontFamily: F.ui, color: C.txtS, marginBottom: 12 }}>
          Drop JSONL here or{' '}
          <label style={{ color: C.acc, cursor: 'pointer' }}>
            Upload Dataset
            <input
              type="file"
              accept=".jsonl,.json"
              style={{ display: 'none' }}
              disabled={uploading}
              onChange={(e) => onFile(e.target.files?.[0])}
            />
          </label>
        </div>
        {uploading && (
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtM }}>Uploading…</div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 1fr' : '1fr', gap: 16 }}>
        <div
          className="mf-card-hover"
          style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 16 }}
        >
          <div
            style={{
              fontFamily: F.mono,
              fontSize: 11,
              letterSpacing: 1,
              color: C.txtM,
              marginBottom: 12,
            }}
          >
            DATASETS ({ds.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {loading ? (
              <LoadingSkeleton rows={4} height={56} />
            ) : ds.length === 0 ? (
              <div style={{ padding: 10, fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.4 }}>
                No datasets yet — datasets are created during evolution or uploaded manually.
              </div>
            ) : (
              ds.map((d) => {
                const isFlashing = flashId === d.dataset_id;
                const created = d.created_at ? new Date(d.created_at) : null;
                const createdLabel = created ? created.toLocaleString() : null;
                const cats = (d.categories || []).filter(Boolean);
                return (
                <button
                  key={d.dataset_id}
                  type="button"
                  onClick={() => openDataset(d.dataset_id)}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '12px 14px',
                    background: isFlashing
                      ? 'rgba(118,185,0,0.12)'
                      : selected === d.dataset_id ? C.bgE : C.bgS,
                    border: `1px solid ${
                      isFlashing ? C.acc : selected === d.dataset_id ? C.acc : C.border
                    }`,
                    borderRadius: 8,
                    cursor: 'pointer',
                    color: C.txtP,
                    fontFamily: F.ui,
                    fontSize: 13,
                    textAlign: 'left',
                    transition: 'background 400ms, border-color 400ms',
                  }}
                >
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ fontFamily: F.mono, color: C.acc }}>{d.dataset_id}</span>
                    <span style={{ color: C.txtM, marginLeft: 8, fontSize: 11 }}>{d.kind}</span>
                    {isFlashing ? (
                      <span style={{ marginLeft: 8, fontSize: 10, color: C.acc, fontFamily: F.mono, letterSpacing: '0.06em' }}>
                        ★ NEW
                      </span>
                    ) : null}
                    <div style={{ fontSize: 11, color: C.txtM, marginTop: 4, fontFamily: F.mono }}>
                      {Number(d.num_samples || 0).toLocaleString()} samples · {Number(d.size_mb || 0).toFixed(2)} MB
                      {createdLabel ? <> · {createdLabel}</> : null}
                    </div>
                    {cats.length ? (
                      <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {cats.slice(0, 6).map((c) => (
                          <span
                            key={c}
                            style={{
                              padding: '1px 6px',
                              fontSize: 10,
                              fontFamily: F.mono,
                              color: C.txtM,
                              background: 'rgba(118,185,0,0.06)',
                              border: `1px solid ${C.border}`,
                              borderRadius: 999,
                            }}
                          >
                            {c}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </span>
                  {d.kind === 'custom' && (
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        if (window.confirm('Delete this dataset?')) deleteDataset(d.dataset_id).then(() => loadList(false));
                      }}
                      onKeyDown={() => {}}
                      style={{ color: C.danger }}
                    >
                      <Trash2 size={16} />
                    </span>
                  )}
                </button>
                );
              })
            )}
          </div>
        </div>

        {selected && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div
              className="mf-card-hover"
              style={{
                background: C.bgC,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                padding: 16,
              }}
            >
              <div style={{ fontFamily: F.ui, fontWeight: 700, color: C.txtP, marginBottom: 12 }}>
                Preview (first 5)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {(preview?.samples || []).map((s, i) => (
                  <div
                    key={i}
                    style={{
                      padding: 12,
                      background: C.bgS,
                      borderRadius: 8,
                      border: `1px solid ${C.border}`,
                      fontSize: 12,
                      color: C.txtS,
                    }}
                  >
                    <div style={{ color: C.ind, marginBottom: 6, fontFamily: F.mono, fontSize: 10 }}>
                      INSTRUCTION
                    </div>
                    <div style={{ marginBottom: 10 }}>{s.instruction}</div>
                    <div style={{ color: C.acc, marginBottom: 6, fontFamily: F.mono, fontSize: 10 }}>
                      RESPONSE
                    </div>
                    <div>{s.response}</div>
                  </div>
                ))}
              </div>
            </div>

            {quality && (
              <div
                className="mf-card-hover"
                style={{
                  background: C.bgC,
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  padding: 16,
                }}
              >
                <div style={{ fontFamily: F.ui, fontWeight: 700, color: C.txtP, marginBottom: 12 }}>
                  Quality
                </div>
                <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtS, marginBottom: 12 }}>
                  Duplicate rate: {quality.duplicate_rate} · Overlap (training):{' '}
                  {quality.overlap_with_training}
                  {quality.embedding_diversity != null && (
                    <> · Diversity: {quality.embedding_diversity?.toFixed?.(3)}</>
                  )}
                </div>
                {histData.length > 0 && (
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer>
                      <BarChart data={histData}>
                        <XAxis dataKey="bucket" tick={{ fill: C.txtM, fontSize: 10 }} />
                        <YAxis tick={{ fill: C.txtM, fontSize: 10 }} />
                        <Tooltip contentStyle={{ background: C.bgE, border: `1px solid ${C.border}` }} />
                        <Bar dataKey="n" fill={C.acc} radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
