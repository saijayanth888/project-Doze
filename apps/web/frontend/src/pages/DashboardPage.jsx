import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { FlaskConical, ChevronRight } from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import EvolutionStatus from '../components/dashboard/EvolutionStatus';
import ChampionCard from '../components/dashboard/ChampionCard';
import LatestGeneration from '../components/dashboard/LatestGeneration';
import ScoreTrends from '../components/dashboard/ScoreTrends';
import ActivityFeed from '../components/dashboard/ActivityFeed';
import EventsFeed from '../components/dashboard/EventsFeed';
import GPUMonitor from '../components/dashboard/GPUMonitor';

const s = (i) => ({ animation: `slide-up-fade 0.4s cubic-bezier(0.16,1,0.3,1) ${i * 60}ms both` });

function modelNameFromConfig(cfg) {
  if (!cfg || typeof cfg !== 'object') return null;
  return cfg.model_id || cfg.base_model || cfg.model || null;
}

function CampaignBanner({ status }) {
  const idx = status.current_experiment ?? 0;
  const total = status.total_experiments ?? 0;
  const results = Array.isArray(status.results) ? status.results : [];
  const running = results.find((r) => (r?.status || '').includes('running')) || null;
  const lastCompleted = [...results].reverse().find((r) => (r?.status || '').includes('completed')) || null;
  const summary = running || lastCompleted || null;
  const model = modelNameFromConfig(summary?.config) || '—';
  const method = summary?.method || summary?.config?.method || 'sequential';

  const tone =
    status.status === 'paused' ? '#fbbf24' :
    status.status === 'stopping' ? '#f97316' :
    '#4ade80';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 16px',
        background: 'var(--bg-card-2, #111827)',
        border: `1px solid ${tone}33`,
        borderLeft: `3px solid ${tone}`,
        borderRadius: 8,
        ...s(0),
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        <FlaskConical size={16} style={{ color: tone, flexShrink: 0 }} />
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{
            fontFamily: F.ui,
            fontSize: 12,
            fontWeight: 600,
            color: C.txtP,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span style={{ color: tone, textTransform: 'uppercase', letterSpacing: 0.4 }}>
              {status.status === 'running' ? 'Campaign running' :
               status.status === 'paused'  ? 'Campaign paused'  :
               status.status === 'stopping' ? 'Campaign stopping' : 'Campaign'}
            </span>
            <span style={{ color: C.txtM, fontWeight: 500 }}>
              · Experiment {Math.min(idx + 1, total || 1)}/{total || '?'}
            </span>
          </div>
          <div style={{
            fontFamily: F.mono,
            fontSize: 11,
            color: C.txtS,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {String(model).split('/').pop()} · {method}
            {' · '}
            <span style={{ color: '#4ade80' }}>{status.completed ?? 0} done</span>
            {(status.failed ?? 0) > 0 ? (
              <> · <span style={{ color: '#f87171' }}>{status.failed} failed</span></>
            ) : null}
          </div>
        </div>
      </div>
      <Link
        to="/campaign"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '6px 10px',
          fontFamily: F.ui,
          fontSize: 11,
          fontWeight: 600,
          color: C.txtP,
          textDecoration: 'none',
          background: 'var(--bg-card-3, #1f2937)',
          border: `1px solid ${C.border}`,
          borderRadius: 6,
        }}
      >
        Open campaign <ChevronRight size={12} />
      </Link>
    </div>
  );
}

export default function DashboardPage() {
  const [campaign, setCampaign] = useState({ status: 'idle' });

  const pollCampaign = useCallback(async () => {
    try {
      const data = await apiFetch('/api/campaigns/status');
      setCampaign(data || { status: 'idle' });
    } catch {
      setCampaign({ status: 'idle' });
    }
  }, []);

  useEffect(() => {
    pollCampaign();
  }, [pollCampaign]);

  useEffect(() => {
    if (campaign.status === 'idle') return;
    const iv = setInterval(pollCampaign, 10_000);
    return () => clearInterval(iv);
  }, [campaign.status, pollCampaign]);

  const showBanner = useMemo(
    () => campaign && campaign.status && campaign.status !== 'idle',
    [campaign],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {showBanner ? <CampaignBanner status={campaign} /> : null}

      {/* Row 1: Evolution (5) + Champion (3.5) + Latest (3.5) */}
      <div style={{ display: 'grid', gridTemplateColumns: '5fr 3.5fr 3.5fr', gap: 16, minHeight: 0, ...s(0) }}>
        <EvolutionStatus />
        <ChampionCard />
        <LatestGeneration />
      </div>

      {/* Row 2: Live phase events (full width) — sits high so the user sees
           "what's happening now" without scrolling. */}
      <div style={{ ...s(1) }}>
        <EventsFeed />
      </div>

      {/* Row 3: Trends (8) + Activity history (4) */}
      <div style={{ display: 'grid', gridTemplateColumns: '8fr 4fr', gap: 16, minHeight: 280, ...s(2) }}>
        <ScoreTrends />
        <ActivityFeed />
      </div>

      {/* Row 4: GPU */}
      <div style={{ ...s(3) }}>
        <GPUMonitor />
      </div>
    </div>
  );
}
