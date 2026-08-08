import { Card } from "./components/Card";
import { EmptyState } from "./components/EmptyState";

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" />
          <span className="brand-name">TradePilot AI</span>
        </div>
        <nav className="app-nav">
          <span className="nav-item nav-item-active">Dashboard</span>
          <span className="nav-item">Trade History</span>
          <span className="nav-item">Settings</span>
        </nav>
      </header>

      <main className="app-main">
        <div className="card-grid">
          <Card
            title="Latest Trade Signal"
            subtitle="From the trading agent"
          >
            <EmptyState message="No agent connected yet. Signals will appear here once Milestone 2 is built." />
          </Card>

          <Card title="Chart Capture" subtitle="TradingView screenshots">
            <EmptyState message="No screenshots captured yet." />
          </Card>

          <Card title="Market Snapshot" subtitle="Live market data">
            <EmptyState message="No market data source connected yet." />
          </Card>

          <Card title="Economic Calendar" subtitle="Upcoming events">
            <EmptyState message="No calendar source connected yet." />
          </Card>

          <Card title="Guardrail Status" subtitle="Safety checks">
            <EmptyState message="No guardrails configured yet." />
          </Card>

          <Card title="Trade History" subtitle="Past decisions and outcomes">
            <EmptyState message="No trade history yet." />
          </Card>
        </div>
      </main>

      <footer className="app-footer">
        <span>TradePilot AI — Milestone 1: UI shell only</span>
      </footer>
    </div>
  );
}

export default App;
