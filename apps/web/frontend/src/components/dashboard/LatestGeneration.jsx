import { useEffect, useMemo, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import Badge from '../shared/Badge';

export default function LatestGeneration() {
  const [gens, setGens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  /** Champion exists in registry but Postgres has no generation rows yet. */
  const [registryWithoutDb, setRegistryWithoutDb] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = (silent = false) => {
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      apiFetch('/api/lineage/generations')
        .then((rows) => {
          if (!cancelled && Array.isArray(rows)) {
            setGens(rows);
            if (rows.length === 0) {
              apiFetch('/api/models/champion')
                .then((c) => {
                  if (cancelled) return;
                  setRegistryWithoutDb(!!c && (c.generation ?? 0) > 0);
                })
                .catch(() => {
                  if (!cancelled) setRegistryWithoutDb(false);
                });
            } else if (!cancelled) {
              setRegistryWithoutDb(false);
            }
          }
        })
        .catch((e) => {
          if (!cancelled) {
            setGens([]);
            setRegistryWithoutDb(false);
            setError(e?.status ? `Request failed (HTTP ${e.status}).` : 'Could not load latest generation.');
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    load(false);
    const iv = setInterval(() => load(true), 5000);

    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, []);

  const gen = useMemo(() => {
    if (!gens.length) return null;
    const sorted = [...gens].sort((a, b) => (a.generation ?? 0) - (b.generation ?? 0));
    return sorted[sorted.length - 1];
  }, [gens]);

  if (loading) {
    return (
      <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM }}>Loading…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
        <div style={{ fontFamily: F.ui, fontSize: 13, color: C.danger, lineHeight: 1.5 }}>
          {error}
        </div>
      </div>
    );
  }

  if (!gen) {
    return (
      <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
        <div style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM, marginBottom: 10 }}>
          Latest Generation
        </div>
        <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.5, margin: 0 }}>
          No generations yet — complete an evolution run to see parent vs child scores here.
        </p>
        {registryWithoutDb ? (
          <p style={{ fontFamily: F.ui, fontSize: 12, color: C.warning, lineHeight: 1.5, margin: '12px 0 0 0' }}>
            A champion is registered, but the lineage database has no generation history yet. After the next evolution
            completes, scores will appear here. If this persists, confirm Postgres is the same instance the API uses.
          </p>
        ) : null}
      </div>
    );
  }

  const parentScores = gen.parent_scores ?? {};
  const childScores = gen.child_scores ?? {};
  const pVals = Object.values(parentScores);
  const cVals = Object.values(childScores);
  const parentAvg = pVals.length ? pVals.reduce((a, b) => a + b, 0) / pVals.length : 0;
  const childAvg = cVals.length ? cVals.reduce((a, b) => a + b, 0) / cVals.length : 0;
  const delta = childAvg - parentAvg;

  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Latest Generation</span>
        <Badge type={gen.promoted ? 'promoted' : 'discarded'}>{gen.promoted ? 'Promoted' : 'Discarded'}</Badge>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 14, alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Parent</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 500, color: C.txtS, lineHeight: 1 }}>{parentAvg.toFixed(3)}</div>
        </div>
        <div style={{ color: delta > 0 ? C.success : C.danger, fontSize: 20, paddingBottom: 2 }}>
          {delta > 0 ? '↑' : '↓'}
        </div>
        <div>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Child</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 500, color: gen.promoted ? C.acc : C.danger, lineHeight: 1 }}>{childAvg.toFixed(3)}</div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 3 }}>Delta</div>
          <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 600, color: delta > 0 ? C.success : C.danger, lineHeight: 1 }}>
            {delta > 0 ? '+' : ''}
            {delta.toFixed(3)}
          </div>
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        {Object.keys(parentScores).map((bench) => {
          const pd = parentScores[bench];
          const cd = childScores[bench];
          const d = cd - pd;
          return (
            <div key={bench} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, width: 110, flexShrink: 0 }}>{bench}</span>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS, width: 48 }}>{pd.toFixed(3)}</span>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: d > 0 ? C.success : d < 0 ? C.danger : C.txtM, width: 56, fontWeight: 600 }}>
                {d > 0 ? '+' : ''}
                {d.toFixed(3)}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
        {gen.training_data_size?.toLocaleString?.() ?? '—'} samples · {gen.decision_reason ?? '—'}
      </div>
    </div>
  );
}
