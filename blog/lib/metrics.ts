import fs from 'fs';
import path from 'path';

export interface RunCosts {
  llm_input_tokens: number;
  llm_output_tokens: number;
  llm_cost_usd: number;
  embedding_tokens: number;
  embedding_cost_usd: number;
  search_calls: number;
  search_cost_usd: number;
  total_cost_usd: number;
}

export interface RunRecord {
  date: string;
  timestamp: string;
  status: 'success' | 'failed';
  topic: string | null;
  slug: string | null;
  rationale: string | null;
  builds_on: string | null;
  duration_seconds: number;
  word_count: number;
  chapter_count: number;
  source_count: number;
  claim_count: number;
  image_count: number;
  costs: RunCosts;
  langsmith_url: string | null;
  error: string | null;
  traceback: string | null;
}

export interface MetricsData {
  runs: RunRecord[];
}

const metricsPath = path.join(process.cwd(), 'data/metrics.json');

export function getMetrics(): MetricsData {
  if (!fs.existsSync(metricsPath)) {
    return { runs: [] };
  }
  const content = fs.readFileSync(metricsPath, 'utf-8');
  return JSON.parse(content);
}

export function getLatestRuns(count: number = 30): RunRecord[] {
  const metrics = getMetrics();
  return metrics.runs.slice(-count).reverse();
}
