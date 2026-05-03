import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';
import LandingPage from './pages/LandingPage';
import DashboardPage from './pages/DashboardPage';
import LineagePage from './pages/LineagePage';
import BenchmarksPage from './pages/BenchmarksPage';
import PlaygroundPage from './pages/PlaygroundPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route element={<Layout />}>
          <Route path="/dashboard"  element={<DashboardPage />} />
          <Route path="/lineage"    element={<LineagePage />} />
          <Route path="/benchmarks" element={<BenchmarksPage />} />
          <Route path="/playground" element={<PlaygroundPage />} />
          <Route path="/settings"   element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
