'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Search,
  MessageSquare,
  Loader2,
  AlertCircle,
  ArrowLeft,
} from 'lucide-react';

interface ThreadContent {
  thread_id: string;
  topic: string;
  phase: string;
  iteration: number;
  word_count: number;
  chapter_count: number;
  source_count: number;
  claim_count: number;
  content: Array<{
    chapter_number: number;
    title: string;
    content: string;
    word_count: number;
  }>;
  references: string;
  warnings: string[];
}

export default function ThreadViewPage() {
  const params = useParams();
  const threadId = params.thread_id as string;

  const [thread, setThread] = useState<ThreadContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentChapter, setCurrentChapter] = useState(0);
  const [showReferences, setShowReferences] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  useEffect(() => {
    const fetchThread = async () => {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        const response = await fetch(`${apiUrl}/api/v1/generation/threads/${threadId}`);

        if (!response.ok) {
          if (response.status === 404) {
            throw new Error('Thread not found');
          }
          throw new Error('Failed to fetch thread');
        }

        const data = await response.json();
        setThread(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load thread');
      } finally {
        setLoading(false);
      }
    };

    if (threadId) {
      fetchThread();
    }
  }, [threadId]);

  const handleDownloadPdf = async () => {
    if (!thread) return;

    setDownloadingPdf(true);
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
      a.download = `${thread.topic.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download PDF');
    } finally {
      setDownloadingPdf(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
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
          </div>
        </header>
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
        </div>
      </main>
    );
  }

  if (error || !thread) {
    return (
      <main className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
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
          </div>
        </header>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-600" />
            <span className="text-red-800">{error || 'Thread not found'}</span>
          </div>
          <Link
            href="/history"
            className="inline-flex items-center gap-2 mt-4 text-primary-600 hover:text-primary-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to History
          </Link>
        </div>
      </main>
    );
  }

  const hasContent = thread.content && thread.content.length > 0;
  const chapter = hasContent ? thread.content[currentChapter] : null;
  const hasReferences = thread.references && thread.references.length > 0;

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
        <div className="mb-6">
          <Link
            href="/history"
            className="inline-flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to History
          </Link>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">{thread.topic}</h2>
              <p className="text-gray-600 mt-1">
                {thread.word_count.toLocaleString()} words across {thread.chapter_count} chapters
              </p>
            </div>
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              <Download className="w-4 h-4" />
              {downloadingPdf ? 'Generating PDF...' : 'Download PDF'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4 mb-6">
          <StatCard icon={FileText} label="Chapters" value={thread.chapter_count} />
          <StatCard icon={BookOpen} label="Words" value={thread.word_count.toLocaleString()} />
          <StatCard icon={Search} label="Sources" value={thread.source_count} />
          <StatCard icon={MessageSquare} label="Claims" value={thread.claim_count} />
        </div>

        {hasContent && chapter ? (
          <div className="grid grid-cols-4 gap-6">
            <div className="col-span-1">
              <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm sticky top-24">
                <h3 className="font-semibold text-gray-900 mb-3">Chapters</h3>
                <nav className="space-y-1">
                  {thread.content.map((ch, index) => (
                    <button
                      key={index}
                      onClick={() => {
                        setCurrentChapter(index);
                        setShowReferences(false);
                      }}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                        currentChapter === index && !showReferences
                          ? 'bg-primary-100 text-primary-700'
                          : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      <div className="font-medium truncate">{ch.title}</div>
                      <div className="text-xs text-gray-500">
                        {ch.word_count.toLocaleString()} words
                      </div>
                    </button>
                  ))}
                  {hasReferences && (
                    <button
                      onClick={() => setShowReferences(true)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors mt-2 border-t border-gray-200 pt-3 ${
                        showReferences
                          ? 'bg-primary-100 text-primary-700'
                          : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      <div className="font-medium">References</div>
                      <div className="text-xs text-gray-500">{thread.source_count} sources</div>
                    </button>
                  )}
                </nav>
              </div>
            </div>

            <div className="col-span-3">
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                {showReferences ? (
                  <>
                    <div className="border-b border-gray-200 px-6 py-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm text-gray-500">Bibliography</div>
                          <h2 className="text-xl font-bold text-gray-900">References</h2>
                        </div>
                        <div className="text-sm text-gray-500">
                          {thread.source_count} sources cited
                        </div>
                      </div>
                    </div>
                    <div className="px-8 py-6 prose prose-lg max-w-none">
                      <ReactMarkdown>{thread.references || ''}</ReactMarkdown>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="border-b border-gray-200 px-6 py-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm text-gray-500">
                            Chapter {chapter.chapter_number}
                          </div>
                          <h2 className="text-xl font-bold text-gray-900">{chapter.title}</h2>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setCurrentChapter(Math.max(0, currentChapter - 1))}
                            disabled={currentChapter === 0}
                            className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <ChevronLeft className="w-5 h-5" />
                          </button>
                          <span className="text-sm text-gray-500">
                            {currentChapter + 1} / {thread.content.length}
                          </span>
                          <button
                            onClick={() =>
                              setCurrentChapter(
                                Math.min(thread.content.length - 1, currentChapter + 1)
                              )
                            }
                            disabled={currentChapter === thread.content.length - 1}
                            className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <ChevronRight className="w-5 h-5" />
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="px-8 py-6 prose prose-lg max-w-none">
                      <ReactMarkdown>{chapter.content}</ReactMarkdown>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
            <AlertCircle className="w-8 h-8 text-amber-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-amber-900 mb-2">No Content Available</h3>
            <p className="text-amber-700">
              This generation may still be in progress or encountered an issue.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-gray-500 mb-1">
        <Icon className="w-4 h-4" />
        <span className="text-sm">{label}</span>
      </div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
    </div>
  );
}
