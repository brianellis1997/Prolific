interface StatsOverviewProps {
  totalRuns: number;
  successCount: number;
  failCount: number;
  totalCost: number;
  pptxSuccess: number;
  pptxFailed: number;
}

function StatCard({ label, value, sublabel }: { label: string; value: string | number; sublabel?: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-100">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sublabel && <p className="text-xs text-gray-400 mt-0.5">{sublabel}</p>}
    </div>
  );
}

export function StatsOverview({ totalRuns, successCount, failCount, totalCost, pptxSuccess, pptxFailed }: StatsOverviewProps) {
  const avgCost = successCount > 0 ? totalCost / successCount : 0;
  const successRate = totalRuns > 0 ? Math.round((successCount / totalRuns) * 100) : 0;
  const pptxTotal = pptxSuccess + pptxFailed;
  const pptxRate = pptxTotal > 0 ? Math.round((pptxSuccess / pptxTotal) * 100) : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-8">
      <StatCard label="Total Runs" value={totalRuns} />
      <StatCard label="Success Rate" value={`${successRate}%`} />
      <StatCard label="Failed" value={failCount} />
      <StatCard label="Total Cost" value={`$${totalCost.toFixed(2)}`} />
      <StatCard label="Avg Cost/Article" value={`$${avgCost.toFixed(2)}`} />
      <StatCard
        label="Presentations"
        value={pptxTotal > 0 ? `${pptxRate}%` : '--'}
        sublabel={pptxTotal > 0 ? `${pptxSuccess}/${pptxTotal} succeeded` : 'No data yet'}
      />
    </div>
  );
}
