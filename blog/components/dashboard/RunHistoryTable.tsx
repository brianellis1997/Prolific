'use client';

import { Fragment, useState } from 'react';
import Link from 'next/link';
import type { RunRecord } from '@/lib/metrics';

interface RunHistoryTableProps {
  runs: RunRecord[];
}

function RunDetail({ run }: { run: RunRecord }) {
  return (
    <div className="space-y-3 text-sm">
      {run.rationale && (
        <div>
          <span className="font-medium text-gray-700">Rationale: </span>
          <span className="text-gray-600">{run.rationale}</span>
        </div>
      )}
      {run.builds_on && (
        <div>
          <span className="font-medium text-gray-700">Builds on: </span>
          <Link href={`/posts/${run.builds_on}`} className="text-sky-600 hover:underline">
            {run.builds_on}
          </Link>
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-gray-600">
        <span>Chapters: {run.chapter_count}</span>
        <span>Sources: {run.source_count}</span>
        <span>Claims: {run.claim_count}</span>
        <span>Images: {run.image_count}</span>
      </div>
      {run.costs && (
        <div className="grid grid-cols-3 gap-2 text-gray-600">
          <span>LLM: ${run.costs.llm_cost_usd?.toFixed(3)}</span>
          <span>Embeddings: ${run.costs.embedding_cost_usd?.toFixed(4)}</span>
          <span>Search: ${run.costs.search_cost_usd?.toFixed(3)} ({run.costs.search_calls} calls)</span>
        </div>
      )}
      {run.presentation && (
        <div className="border border-gray-200 rounded-lg p-3 bg-white">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-medium text-gray-700">Presentation</span>
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                run.presentation.status === 'success'
                  ? 'bg-green-100 text-green-700'
                  : run.presentation.status === 'failed'
                  ? 'bg-red-100 text-red-700'
                  : 'bg-yellow-100 text-yellow-700'
              }`}
            >
              {run.presentation.status}
            </span>
          </div>
          {run.presentation.status === 'success' && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-gray-600 mb-2">
                <span>Slides: {run.presentation.slide_count}</span>
                <span>Images: {run.presentation.images_embedded}/{run.presentation.images_available}</span>
                <span>Notes: {run.presentation.has_speaker_notes ? 'Yes' : 'Missing'}</span>
                <span>Time: {run.presentation.duration_seconds}s</span>
              </div>
              {run.presentation.slide_types && Object.keys(run.presentation.slide_types).length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {Object.entries(run.presentation.slide_types).map(([type, count]) => (
                    <span key={type} className="px-2 py-0.5 bg-gray-100 rounded text-xs text-gray-600">
                      {type}: {count}
                    </span>
                  ))}
                </div>
              )}
              {run.presentation.images_failed > 0 && (
                <p className="text-amber-600 text-xs mt-1">
                  {run.presentation.images_failed} image(s) failed to embed
                </p>
              )}
            </>
          )}
          {run.presentation.status === 'failed' && run.presentation.error && (
            <div className="text-red-600 text-xs mt-1">
              <span className="font-medium">Stage: </span>{run.presentation.error_stage || 'unknown'}
              <br />
              {run.presentation.error}
            </div>
          )}
        </div>
      )}
      {run.langsmith_url && (
        <div>
          <a
            href={run.langsmith_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sky-600 hover:underline text-sm"
          >
            View Trace in LangSmith
          </a>
        </div>
      )}
      {run.error && (
        <div>
          <span className="font-medium text-red-600">Error: </span>
          <span className="text-red-600">{run.error}</span>
          {run.traceback && (
            <pre className="mt-2 p-3 bg-gray-900 text-gray-100 rounded-lg text-xs overflow-x-auto whitespace-pre-wrap">
              {run.traceback}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function RunHistoryTable({ runs }: RunHistoryTableProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (runs.length === 0) {
    return (
      <div>
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Run History</h2>
        <p className="text-gray-500 text-sm">No runs recorded yet.</p>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Run History</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="py-2 pr-4">Date</th>
              <th className="py-2 pr-4">Topic</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">PPTX</th>
              <th className="py-2 pr-4">Words</th>
              <th className="py-2 pr-4">Cost</th>
              <th className="py-2 pr-4">Duration</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run, idx) => (
              <Fragment key={idx}>
                <tr
                  className="border-b border-gray-100 cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                >
                  <td className="py-3 pr-4 text-gray-600">{run.date}</td>
                  <td className="py-3 pr-4 text-gray-900 max-w-xs truncate">
                    {run.slug ? (
                      <Link
                        href={`/posts/${run.slug}`}
                        className="text-sky-600 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {run.topic}
                      </Link>
                    ) : (
                      run.topic || 'N/A'
                    )}
                  </td>
                  <td className="py-3 pr-4">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        run.status === 'success'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    {run.presentation ? (
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          run.presentation.status === 'success'
                            ? 'bg-green-100 text-green-700'
                            : run.presentation.status === 'failed'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-yellow-100 text-yellow-700'
                        }`}
                      >
                        {run.presentation.status === 'success'
                          ? `${run.presentation.slide_count} slides`
                          : run.presentation.status}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">--</span>
                    )}
                  </td>
                  <td className="py-3 pr-4 text-gray-600">{run.word_count.toLocaleString()}</td>
                  <td className="py-3 pr-4 text-gray-600">
                    ${(run.costs?.total_cost_usd || 0).toFixed(2)}
                  </td>
                  <td className="py-3 pr-4 text-gray-600">
                    {Math.round(run.duration_seconds / 60)}m
                  </td>
                </tr>
                {expandedIdx === idx && (
                  <tr>
                    <td colSpan={7} className="py-4 px-4 bg-gray-50">
                      <RunDetail run={run} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

