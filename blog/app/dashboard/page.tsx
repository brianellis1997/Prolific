import { getMetrics } from '@/lib/metrics';
import { StatsOverview } from '@/components/dashboard/StatsOverview';
import { CostSummary } from '@/components/dashboard/CostSummary';
import { RunHistoryTable } from '@/components/dashboard/RunHistoryTable';

export const metadata = {
  title: 'Pipeline Dashboard',
};

export default function DashboardPage() {
  const metrics = getMetrics();
  const runs = metrics.runs.slice().reverse();

  const totalCost = runs.reduce((sum, r) => sum + (r.costs?.total_cost_usd || 0), 0);
  const successCount = runs.filter(r => r.status === 'success').length;
  const failCount = runs.filter(r => r.status === 'failed').length;
  const pptxSuccess = runs.filter(r => r.presentation?.status === 'success').length;
  const pptxFailed = runs.filter(r => r.presentation?.status === 'failed').length;

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">Pipeline Dashboard</h1>

      <StatsOverview
        totalRuns={runs.length}
        successCount={successCount}
        failCount={failCount}
        totalCost={totalCost}
        pptxSuccess={pptxSuccess}
        pptxFailed={pptxFailed}
      />

      <CostSummary runs={runs} />

      <RunHistoryTable runs={runs} />
    </div>
  );
}
