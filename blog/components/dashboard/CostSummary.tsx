'use client';

import type { RunRecord } from '@/lib/metrics';

interface CostSummaryProps {
  runs: RunRecord[];
}

export function CostSummary({ runs }: CostSummaryProps) {
  const successRuns = runs.filter(r => r.status === 'success');
  const last10 = successRuns.slice(0, 10);

  if (last10.length === 0) {
    return (
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Cost per Run</h2>
        <p className="text-gray-500 text-sm">No successful runs yet.</p>
      </div>
    );
  }

  const maxCost = Math.max(...last10.map(r => r.costs?.total_cost_usd || 0), 0.01);

  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Cost per Run (Last 10)</h2>
      <div className="space-y-2">
        {last10.map((run, i) => {
          const cost = run.costs?.total_cost_usd || 0;
          const width = (cost / maxCost) * 100;
          return (
            <div key={i} className="flex items-center gap-3">
              <span className="text-xs text-gray-400 w-20 shrink-0">{run.date}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-5 overflow-hidden">
                <div
                  className="bg-sky-500 h-full rounded-full transition-all"
                  style={{ width: `${width}%` }}
                />
              </div>
              <span className="text-sm text-gray-600 w-16 text-right">${cost.toFixed(2)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
