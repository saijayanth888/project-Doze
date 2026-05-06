import EvolutionStatus from '../components/dashboard/EvolutionStatus';
import ChampionCard from '../components/dashboard/ChampionCard';
import LatestGeneration from '../components/dashboard/LatestGeneration';
import ScoreTrends from '../components/dashboard/ScoreTrends';
import ActivityFeed from '../components/dashboard/ActivityFeed';
import EventsFeed from '../components/dashboard/EventsFeed';
import GPUMonitor from '../components/dashboard/GPUMonitor';

const s = (i) => ({ animation: `slide-up-fade 0.4s cubic-bezier(0.16,1,0.3,1) ${i * 60}ms both` });

export default function DashboardPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
