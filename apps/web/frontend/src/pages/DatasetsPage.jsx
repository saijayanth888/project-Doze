import { useCallback, useEffect, useState } from 'react';
import { Database, Trash2, Upload } from 'lucide-react';
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

export default function DatasetsPage() {
  const [list, setList] = useState(null);
  const [warn, setWarn] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [preview, setPreview] = useState(null);
  const [quality, setQuality] = useState(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchDatasets();
      setList(d);
      setWarn(null);
    } catch (e) {
      setList({ datasets: [], total: 0 });
      const st = e?.status;
      setWarn(st === 401 || st === 403 ? 'API key not configured — check Settings.' : 'Could not load datasets — check API connectivity.');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

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
        <div>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Datasets</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Curated evolution data and custom JSONL uploads
          </p>
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
              <div style={{ padding: 10, fontFamily: F.ui, fontSize: 13, color: C.txtM }}>Loading datasets…</div>
            ) : ds.length === 0 ? (
              <div style={{ padding: 10, fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.4 }}>
                No datasets yet — datasets are created during evolution or uploaded manually.
              </div>
            ) : (
              ds.map((d) => (
                <button
                  key={d.dataset_id}
                  type="button"
                  onClick={() => openDataset(d.dataset_id)}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '12px 14px',
                    background: selected === d.dataset_id ? C.bgE : C.bgS,
                    border: `1px solid ${selected === d.dataset_id ? C.acc : C.border}`,
                    borderRadius: 8,
                    cursor: 'pointer',
                    color: C.txtP,
                    fontFamily: F.ui,
                    fontSize: 13,
                    textAlign: 'left',
                  }}
                >
                  <span>
                    <span style={{ fontFamily: F.mono, color: C.acc }}>{d.dataset_id}</span>
                    <span style={{ color: C.txtM, marginLeft: 8, fontSize: 11 }}>{d.kind}</span>
                    <div style={{ fontSize: 11, color: C.txtM, marginTop: 4 }}>
                      {d.num_samples} samples · {Number(d.size_mb || 0).toFixed(2)} MB
                    </div>
                  </span>
                  {d.kind === 'custom' && (
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        if (window.confirm('Delete this dataset?')) deleteDataset(d.dataset_id).then(loadList);
                      }}
                      onKeyDown={() => {}}
                      style={{ color: C.danger }}
                    >
                      <Trash2 size={16} />
                    </span>
                  )}
                </button>
              ))
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
