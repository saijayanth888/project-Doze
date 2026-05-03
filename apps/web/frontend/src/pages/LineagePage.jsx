import { useCallback, useEffect, useState } from 'react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import LineageTree from '../components/lineage/LineageTree';
import LineageDetail from '../components/lineage/LineageDetail';
import Button from '../components/shared/Button';

function StatCard({ label, value, color }) {
  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '12px 16px' }}>
      <div style={{ fontFamily: F.ui, fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: F.mono, fontSize: '1.8rem', fontWeight: 500, color: color || C.txtP, lineHeight: 1 }}>{value}</div>
    </div>
  );
}

export default function LineagePage() {
  const [tree, setTree] = useState(undefined);
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    setTree(undefined);
    setErr(null);
    apiFetch('/api/lineage/tree')
      .then((d) => {
        setTree(d);
      })
      .catch((e) => {
        setErr(e?.message || String(e));
        setTree(null);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (tree === undefined) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', fontFamily: F.mono, fontSize: 13, color: C.txtM }}>
        Loading lineage…
      </div>
    );
  }

  if (tree === null || !tree.nodes) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, minHeight: '50vh', padding: 24 }}>
        <p style={{ fontFamily: F.mono, fontSize: 14, color: C.danger, textAlign: 'center', maxWidth: 420 }}>{err || 'Could not load lineage tree.'}</p>
        <Button variant="primary" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  const data = tree;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        flex: 1,
        minHeight: 0,
        width: '100%',
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
        <StatCard label="Total Nodes" value={data.total_nodes} />
        <StatCard label="Promoted" value={data.total_promoted} color={C.acc} />
        <StatCard label="Discarded" value={data.total_discarded} color={C.danger} />
        <StatCard label="Champion" value={`#${data.champion_id?.replace('gen-', '')}`} color={C.acc} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: 'rgba(118,185,0,0.2)', border: `2px solid ${C.acc}` }} />
          <span style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM }}>Promoted</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: 'rgba(239,68,68,0.15)', border: `2px solid ${C.danger}` }} />
          <span style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM }}>Discarded</span>
        </div>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginLeft: 'auto' }}>Scroll to zoom · Drag to pan · Click node for details</span>
      </div>

      <div style={{ position: 'relative', width: '100%', flex: 1, minHeight: 400 }}>
        <LineageTree nodes={data.nodes} edges={data.edges} onNodeClick={setSelected} selectedNode={selected} />
        {selected && <LineageDetail node={selected} allNodes={data.nodes} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
