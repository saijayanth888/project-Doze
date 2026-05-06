import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';

const LandingPage = lazy(() => import('./pages/LandingPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const AdaptersPage = lazy(() => import('./pages/AdaptersPage'));
const LineagePage = lazy(() => import('./pages/LineagePage'));
const DatasetsPage = lazy(() => import('./pages/DatasetsPage'));
const BenchmarksPage = lazy(() => import('./pages/BenchmarksPage'));
const PlaygroundPage = lazy(() => import('./pages/PlaygroundPage'));
const ForgeAgentPage = lazy(() => import('./pages/ForgeAgentPage'));
const AutomationPage = lazy(() => import('./pages/AutomationPage'));
const EPTPage = lazy(() => import('./pages/EPTPage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

function PageFallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '40vh',
        color: 'var(--text-muted, #64748b)',
        fontFamily: 'var(--font-mono, monospace)',
        fontSize: 13,
      }}
    >
      Loading…
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/adapters" element={<AdaptersPage />} />
            <Route path="/lineage" element={<LineagePage />} />
            <Route path="/datasets" element={<DatasetsPage />} />
            <Route path="/benchmarks" element={<BenchmarksPage />} />
            <Route path="/playground" element={<PlaygroundPage />} />
            <Route path="/forge" element={<ForgeAgentPage />} />
            <Route path="/ept" element={<EPTPage />} />
            <Route path="/automation" element={<AutomationPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
