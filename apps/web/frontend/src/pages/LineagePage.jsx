import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownToLine, ArrowUpRight, GitBranch, GitCompare, MessageSquare, Trophy } from 'lucide-react';
import { BENCH_COLORS, C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import LineageTree from '../components/lineage/LineageTree';
import LineageDetail from '../components/lineage/LineageDetail';
import Button from '../components/shared/Button';

const POLL_FAST_MS = 5000;   // active-run polling
const POLL_SLOW_MS = 20000;  // idle polling

const BENCH_KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];
const BENCH_LABELS = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-C',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

function scoresOf(n) {
  if (!n) return {};
  return n.scores || n.childScores || n.child_scores || {};
}

function downloadGenerationReport(gen) {
  const childScores = scoresOf(gen);
  const vals = Object.values(childScores).filter((v) => typeof v === 'number');
  const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  const report = {
    run_id: gen.run_id ?? null,
    generation: gen.generation ?? null,
    promoted: !!gen.promoted,
    is_champion: !!gen.is_champion,
    decision_reason: gen.decision_reason ?? null,
    method: gen.method ?? null,
    avg_score: Number(avg.toFixed(4)),
    scores: childScores,
    parent_scores: gen.parent_scores ?? null,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const safeRun = String(gen.run_id || gen.id || 'gen').replace(/[^a-zA-Z0-9._-]/g, '_');
  a.href = url;
  a.download = `${safeRun}-gen${gen.generation ?? 0}-report.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Compact horizontal score-bar row used in the timeline strip. */
function BenchBars({ scores }) {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end', height: 28 }}>
      {BENCH_KEYS.map((k) => {
        const v = typeof scores?.[k] === 'number' ? scores[k] : 0;
        const pct = Math.max(2, Math.min(100, v * 100));
        return (
          <div
            key={k}
            title={`${BENCH_LABELS[k]}: ${typeof scores?.[k] === 'number' ? v.toFixed(3) : '—'}`}
            style={{
              width: 14,
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'flex-end',
              cursor: 'help',
            }}
          >
            <div
              style={{
                height: `${pct}%`,
                background: BENCH_COLORS[k] || '#94a3b8',
                borderRadius: 2,
                opacity: typeof scores?.[k] === 'number' ? 0.85 : 0.18,
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

function GenerationTimelineCard({ gen, isSelected, onSelect, championAdapterId }) {
  const childScores = scoresOf(gen);
  const vals = Object.values(childScores).filter((v) => typeof v === 'number');
  const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : (gen.avg_score ?? 0);
  const promoted = !!gen.promoted;
  const isChamp = !!gen.is_champion;

  const tone = isChamp
    ? { border: 'rgba(212,165,116,0.55)', bg: 'rgba(212,165,116,0.06)', text: '#d4a574' }
    : promoted
      ? { border: 'rgba(118,185,0,0.45)', bg: 'rgba(118,185,0,0.05)', text: C.acc }
      : { border: 'rgba(239,68,68,0.45)', bg: 'rgba(239,68,68,0.04)', text: C.danger };

  return (
    <button
      type="button"
      onClick={() => onSelect(gen)}
      style={{
        textAlign: 'left',
        background: tone.bg,
        border: `1px solid ${isSelected ? tone.text : tone.border}`,
        borderLeftWidth: 4,
        borderLeftColor: tone.text,
        borderRadius: 8,
        padding: '12px 14px',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minWidth: 0,
        opacity: !promoted && !isChamp ? 0.85 : 1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isChamp ? <Trophy size={14} color={tone.text} /> : null}
          <span style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP, fontWeight: 600 }}>
            Generation {gen.generation}
          </span>
          <span
            style={{
              fontFamily: F.ui,
              fontSize: 10,
              padding: '1px 6px',
              borderRadius: 999,
              color: tone.text,
              border: `1px solid ${tone.text}55`,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            {isChamp ? 'champion' : promoted ? 'promoted' : 'discarded'}
          </span>
        </div>
        <span style={{ fontFamily: F.mono, fontSize: 16, color: tone.text, fontWeight: 500 }}>
          {Number(avg).toFixed(3)}
        </span>
      </div>

      <BenchBars scores={childScores} />

      {gen.decision_reason ? (
        <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, lineHeight: 1.4 }}>
          {String(gen.decision_reason).slice(0, 140)}
        </div>
      ) : null}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
        {/* Open in Playground — adapter is auto-selected via existing Playground default */}
        <Link
          to="/playground"
          onClick={(e) => e.stopPropagation()}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontFamily: F.ui,
            fontSize: 10,
            padding: '3px 8px',
            color: C.txtS,
            background: 'rgba(255,255,255,0.03)',
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            textDecoration: 'none',
          }}
        >
          <MessageSquare size={11} /> Playground
        </Link>
        {/* Compare against current champion via Adapters page (already has the modal) */}
        <Link
          to={`/adapters?compare_b=${encodeURIComponent(gen.id || '')}${championAdapterId ? `&compare_a=${encodeURIComponent(championAdapterId)}` : ''}`}
          onClick={(e) => e.stopPropagation()}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontFamily: F.ui,
            fontSize: 10,
            padding: '3px 8px',
            color: C.txtS,
            background: 'rgba(255,255,255,0.03)',
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            textDecoration: 'none',
          }}
        >
          <GitCompare size={11} /> Compare
        </Link>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); downloadGenerationReport(gen); }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontFamily: F.ui,
            fontSize: 10,
            padding: '3px 8px',
            color: C.txtS,
            background: 'rgba(255,255,255,0.03)',
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          <ArrowDownToLine size={11} /> Report
        </button>
      </div>
    </button>
  );
}

export default function LineagePage() {
  const [tree, setTree] = useState(undefined);
  const [selected, setSelected] = useState(null);
  const [evolve, setEvolve] = useState(null);   // /api/evolve/status — drives polling rate
  const [champion, setChampion] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback((options = {}) => {
    const silent = options.silent === true;
    if (!silent) {
      setTree(undefined);
      setErr(null);
    }
    Promise.all([
      apiFetch('/api/lineage/tree').catch((e) => { throw e; }),
      apiFetch('/api/models/champion').catch(() => null),
      apiFetch('/api/evolve/status').catch(() => null),
    ])
      .then(([t, c, ev]) => {
        setTree(t);
        setChampion(c);
        setEvolve(ev);
      })
      .catch((e) => {
        if (!silent) {
          setErr(e?.message || String(e));
          setTree(null);
        }
      });
  }, []);

  useEffect(() => {
    load({ silent: false });
  }, [load]);

  // Adaptive polling: 5s while a run is active so a fresh gen card pops in
  // immediately, otherwise 20s to keep CPU low.
  useEffect(() => {
    const fast = evolve?.is_running === true || evolve?.status === 'running';
    const ms = fast ? POLL_FAST_MS : POLL_SLOW_MS;
    const iv = setInterval(() => load({ silent: true }), ms);
    return () => clearInterval(iv);
  }, [evolve?.is_running, evolve?.status, load]);

  // When the tree refreshes, default the selected node to the current champion
  // (or the first node) so the right pane is never blank.
  const defaultSelected = useMemo(() => {
    if (!tree?.nodes?.length) return null;
    return (
      tree.nodes.find((n) => n.is_champion) ||
      tree.nodes.find((n) => n.id === tree.champion_id) ||
      tree.nodes[tree.nodes.length - 1]
    );
  }, [tree]);

  useEffect(() => {
    if (!selected && defaultSelected) setSelected(defaultSelected);
  }, [defaultSelected, selected]);

  const baseModel = champion?.base_model || null;

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
        <p style={{ fontFamily: F.mono, fontSize: 14, color: C.danger, textAlign: 'center', maxWidth: 420 }}>
          {err || 'Could not load lineage tree.'}
        </p>
        <Button variant="primary" onClick={() => load({ silent: false })}>Retry</Button>
      </div>
    );
  }

  const data = tree;
  const sortedNodes = [...(data.nodes || [])].sort(
    (a, b) => (b.generation ?? 0) - (a.generation ?? 0)
  );
  const isLive = evolve?.is_running === true || evolve?.status === 'running';

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        flex: 1,
        minHeight: 0,
        width: '100%',
      }}
    >
      {/* Slim header strip — replaces the four big KPI cards */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          padding: '10px 14px',
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <GitBranch size={14} color={C.acc} />
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
            Lineage
          </span>
        </div>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
          <span style={{ color: C.txtS }}>{data.total_nodes}</span> nodes ·
          <span style={{ color: C.acc, marginLeft: 4 }}>{data.total_promoted}</span> promoted ·
          <span style={{ color: C.danger, marginLeft: 4 }}>{data.total_discarded}</span> discarded
        </span>
        {data.champion_id ? (
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
            champion: <span style={{ color: C.acc }}>{data.champion_id}</span>
          </span>
        ) : null}
        {baseModel ? (
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
            base: <span style={{ color: C.txtS }}>{baseModel}</span>
          </span>
        ) : null}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: 999,
              background: isLive ? C.acc : C.txtM,
              boxShadow: isLive ? `0 0 8px ${C.acc}` : 'none',
              animation: isLive ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
          <span style={{ fontFamily: F.mono, fontSize: 10, color: isLive ? C.acc : C.txtM, letterSpacing: '0.06em' }}>
            {isLive ? `LIVE · gen ${evolve?.generation ?? '?'} · ${evolve?.current_step || '…'}` : 'idle'}
          </span>
        </div>
      </div>

      {/* Tree (70%) + persistent detail (30%) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 7fr) minmax(280px, 3fr)',
          gap: 14,
          minHeight: 360,
          flexShrink: 0,
        }}
      >
        <div style={{ position: 'relative', minHeight: 360 }}>
          <LineageTree
            nodes={data.nodes}
            edges={data.edges}
            onNodeClick={(n) => setSelected(n.synthetic ? null : n)}
            selectedNode={selected}
            baseModel={baseModel}
          />
          <div
            style={{
              position: 'absolute',
              top: 12,
              right: 12,
              fontFamily: F.mono,
              fontSize: 10,
              color: C.txtM,
              background: 'rgba(0,0,0,0.35)',
              padding: '4px 8px',
              borderRadius: 6,
              border: `1px solid ${C.border}`,
              pointerEvents: 'none',
            }}
          >
            scroll = zoom · drag = pan · click node = focus
          </div>
        </div>

        {/* Persistent detail panel (rendered without absolute positioning so it
             sits inline rather than overlaying the SVG). */}
        <div
          style={{
            position: 'relative',
            background: '#0c1018',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            overflow: 'hidden',
            minHeight: 360,
          }}
        >
          {selected ? (
            <div style={{ position: 'absolute', inset: 0 }}>
              <LineageDetail
                node={selected}
                allNodes={data.nodes}
                onClose={() => setSelected(defaultSelected)}
              />
            </div>
          ) : (
            <div style={{ padding: 20, fontFamily: F.ui, fontSize: 13, color: C.txtM }}>
              Click a generation node to inspect its scores.
            </div>
          )}
        </div>
      </div>

      {/* Generations timeline — newest first, full-width grid */}
      <div
        style={{
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>
            Generations
          </span>
          <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
            {sortedNodes.length} total · newest first
          </span>
        </div>
        {sortedNodes.length === 0 ? (
          <div style={{ padding: '30px 16px', textAlign: 'center', fontFamily: F.ui, fontSize: 13, color: C.txtM }}>
            No generations yet — once an evolution run completes its first gen, it will appear here.
          </div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
              gap: 10,
            }}
          >
            {sortedNodes.map((g) => (
              <GenerationTimelineCard
                key={g.id || g.generation}
                gen={g}
                isSelected={selected?.id === g.id}
                onSelect={setSelected}
                championAdapterId={champion?.adapter_id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
