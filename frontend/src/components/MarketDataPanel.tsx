import type { MarketDataOut } from "../api/types";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";
import { SourceModeBadge } from "./DemoBadge";

interface MarketDataPanelProps {
  marketData: MarketDataOut | undefined;
}

export function MarketDataPanel({ marketData }: MarketDataPanelProps) {
  if (!marketData) {
    return <EmptyState message="No market data has been fetched yet." />;
  }

  if (marketData.status !== "SUCCESS") {
    return <ErrorNotice title="Market data fetch failed" message={marketData.error_message} />;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SourceModeBadge mode={marketData.mode} />
        {marketData.timestamp && (
          <span className="text-xs text-slate-500">
            quoted {new Date(marketData.timestamp).toLocaleString()}
          </span>
        )}
      </div>
      <p className="text-2xl font-semibold text-slate-100">
        {marketData.price ?? "—"}
        <span className="ml-2 text-sm font-normal text-slate-500">{marketData.symbol}</span>
      </p>
      <p className="text-xs text-slate-500">source: {marketData.source}</p>
    </div>
  );
}
