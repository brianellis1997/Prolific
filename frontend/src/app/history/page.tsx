'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BookOpen,
  Clock,
  FileText,
  Trash2,
  Eye,
  Download,
  ChevronRight,
  AlertCircle,
  Loader2,
} from 'lucide-react';

interface ThreadSummary {
  thread_id: string;
  topic: string;
  phase: string;
  created_at?: string;
  word_count?: number;
  chapter_count?: number;
  source_count?: number;
}

export default function HistoryPage() {
  const router = useRouter();
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchThreads = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/generation/threads`);

      if (!response.ok) {
        throw new Error('Failed to fetch threads');
      }

      const data = await response.json();
      setThreads(data.threads || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchThreads();
  }, []);

  const handleDelete = async (threadId: string) => {
    if (!confirm('Are you sure you want to delete this generation?')) {
      return;
    }

    setDeletingId(threadId);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/generation/threads/${threadId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error('Failed to delete thread');
      }

      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
    } catch (err) {
      alert('Failed to delete thread');
    } finally {
      setDeletingId(null);
    }
  };

  const handleDownloadPdf = async (threadId: string, topic: string) => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/v1/generation/threads/${threadId}/pdf`);

      if (!response.ok) {
        throw new Error('Failed to generate PDF');
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${topic.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download PDF');
    }
  };

  const getPhaseColor = (phase: string) => {
    switch (phase) {
      case 'done':
        return 'bg-green-100 text-green-800';
      case 'research':
        return 'bg-blue-100 text-blue-800';
      case 'writing':
        return 'bg-purple-100 text-purple-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getPhaseLabel = (phase: string) => {
    switch (phase) {
      case 'done':
        return 'Complete';
      case 'research':
        return 'Researching';
      case 'writing':
        return 'Writing';
      case 'verify':
        return 'Verifying';
      case 'extract':
        return 'Extracting';
      default:
        return phase;
    }
  };

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/" className="flex items-center gap-3">
                <div className="bg-primary-500 p-2 rounded-lg">
                  <BookOpen className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h1 className="text-xl font-bold text-gray-900">Prolific</h1>
                  <p className="text-sm text-gray-500">AI Content Generation</p>
                </div>
              </Link>
            </div>
            <nav className="flex items-center gap-4">
              <Link
                href="/"
                className="text-sm text-gray-600 hover:text-gray-900 px-3 py-2 rounded-lg hover:bg-gray-100"
              >
                New Generation
              </Link>
              <Link
                href="/history"
                className="text-sm text-primary-600 font-medium px-3 py-2 rounded-lg bg-primary-50"
              >
                History
              </Link>
            </nav>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h2 className="text-2xl font-bold text-gray-900">Generation History</h2>
          <p className="text-gray-600 mt-1">View and manage your past content generations</p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-600" />
            <span className="text-red-800">{error}</span>
          </div>
        )}

        {!loading && !error && threads.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <Clock className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No generations yet</h3>
            <p className="text-gray-600 mb-6">
              Start generating content to see your history here.
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
            >
              Create New Generation
              <ChevronRight className="w-4 h-4" />
            </Link>
          </div>
        )}

        {!loading && !error && threads.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="divide-y divide-gray-200">
              {threads.map((thread) => (
                <div
                  key={thread.thread_id}
                  className="p-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="text-lg font-medium text-gray-900 truncate">
                          {thread.topic}
                        </h3>
                        <span
                          className={`px-2 py-0.5 text-xs font-medium rounded-full ${getPhaseColor(
                            thread.phase
                          )}`}
                        >
                          {getPhaseLabel(thread.phase)}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-sm text-gray-500">
                        {thread.word_count !== undefined && (
                          <span className="flex items-center gap-1">
                            <FileText className="w-4 h-4" />
                            {thread.word_count.toLocaleString()} words
                          </span>
                        )}
                        {thread.chapter_count !== undefined && (
                          <span>{thread.chapter_count} chapters</span>
                        )}
                        {thread.source_count !== undefined && (
                          <span>{thread.source_count} sources</span>
                        )}
                        <span className="font-mono text-xs text-gray-400">
                          {thread.thread_id.slice(0, 8)}...
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-4">
                      <Link
                        href={`/history/${thread.thread_id}`}
                        className="p-2 text-gray-600 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-colors"
                        title="View"
                      >
                        <Eye className="w-5 h-5" />
                      </Link>
                      <button
                        onClick={() => handleDownloadPdf(thread.thread_id, thread.topic)}
                        className="p-2 text-gray-600 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-colors"
                        title="Download PDF"
                      >
                        <Download className="w-5 h-5" />
                      </button>
                      <button
                        onClick={() => handleDelete(thread.thread_id)}
                        disabled={deletingId === thread.thread_id}
                        className="p-2 text-gray-600 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
                        title="Delete"
                      >
                        {deletingId === thread.thread_id ? (
                          <Loader2 className="w-5 h-5 animate-spin" />
                        ) : (
                          <Trash2 className="w-5 h-5" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
