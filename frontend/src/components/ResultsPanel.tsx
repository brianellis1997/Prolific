'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  BookOpen,
  Download,
  Copy,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Search,
  MessageSquare,
  AlertTriangle,
  Sparkles
} from 'lucide-react';

interface ResultsPanelProps {
  result: {
    status: string;
    topic: string;
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
    references?: string;
    warnings: string[];
  };
  onReset: () => void;
}

export function ResultsPanel({ result, onReset }: ResultsPanelProps) {
  const [currentChapter, setCurrentChapter] = useState(0);
  const [copied, setCopied] = useState(false);
  const [showReferences, setShowReferences] = useState(false);

  const hasContent = result.content && result.content.length > 0;
  const chapter = hasContent ? result.content[currentChapter] : null;
  const hasReferences = result.references && result.references.length > 0;

  const copyToClipboard = async () => {
    let fullContent = result.content
      .map((c) => `# ${c.title}\n\n${c.content}`)
      .join('\n\n---\n\n');

    if (result.references) {
      fullContent += result.references;
    }

    await navigator.clipboard.writeText(fullContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadMarkdown = () => {
    let fullContent = result.content
      .map((c) => `# ${c.title}\n\n${c.content}`)
      .join('\n\n---\n\n');

    if (result.references) {
      fullContent += result.references;
    }

    const blob = new Blob([fullContent], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${result.topic.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="max-w-6xl mx-auto">
      {/* Success Banner */}
      <div className="bg-green-50 border border-green-200 rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-green-100 p-2 rounded-lg">
              <Check className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-green-900">
                Generation Complete!
              </h2>
              <p className="text-green-700">
                {result.word_count.toLocaleString()} words across {result.chapter_count} chapters
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={copyToClipboard}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              {copied ? (
                <Check className="w-4 h-4 text-green-600" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
              {copied ? 'Copied!' : 'Copy All'}
            </button>
            <button
              onClick={downloadMarkdown}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
            >
              <Download className="w-4 h-4" />
              Download
            </button>
          </div>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard icon={FileText} label="Chapters" value={result.chapter_count} />
        <StatCard icon={BookOpen} label="Words" value={result.word_count.toLocaleString()} />
        <StatCard icon={Search} label="Sources" value={result.source_count} />
        <StatCard icon={MessageSquare} label="Claims" value={result.claim_count} />
      </div>

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-2 text-amber-800 mb-2">
            <AlertTriangle className="w-5 h-5" />
            <span className="font-medium">Quality Notes</span>
          </div>
          <ul className="text-sm text-amber-700 space-y-1">
            {result.warnings.slice(0, 5).map((warning, i) => (
              <li key={i}>• {warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Content Area */}
      {hasContent && chapter ? (
        <div className="grid grid-cols-4 gap-6">
          {/* Chapter List */}
          <div className="col-span-1">
            <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm sticky top-24">
              <h3 className="font-semibold text-gray-900 mb-3">Chapters</h3>
              <nav className="space-y-1">
                {result.content.map((ch, index) => (
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
                    <div className="text-xs text-gray-500">
                      {result.source_count} sources
                    </div>
                  </button>
                )}
              </nav>
            </div>
          </div>

          {/* Content View */}
          <div className="col-span-3">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              {showReferences ? (
                <>
                  {/* References Header */}
                  <div className="border-b border-gray-200 px-6 py-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm text-gray-500">Bibliography</div>
                        <h2 className="text-xl font-bold text-gray-900">References</h2>
                      </div>
                      <div className="text-sm text-gray-500">
                        {result.source_count} sources cited
                      </div>
                    </div>
                  </div>

                  {/* References Content */}
                  <div className="px-8 py-6 prose prose-lg max-w-none">
                    <ReactMarkdown>{result.references || ''}</ReactMarkdown>
                  </div>
                </>
              ) : (
                <>
                  {/* Chapter Header */}
                  <div className="border-b border-gray-200 px-6 py-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm text-gray-500">
                          Chapter {chapter.chapter_number}
                        </div>
                        <h2 className="text-xl font-bold text-gray-900">
                          {chapter.title}
                        </h2>
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
                          {currentChapter + 1} / {result.content.length}
                        </span>
                        <button
                          onClick={() =>
                            setCurrentChapter(Math.min(result.content.length - 1, currentChapter + 1))
                          }
                          disabled={currentChapter === result.content.length - 1}
                          className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <ChevronRight className="w-5 h-5" />
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Chapter Content */}
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
          <AlertTriangle className="w-8 h-8 text-amber-600 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-amber-900 mb-2">No Content Generated</h3>
          <p className="text-amber-700">The generation completed but no chapters were created. This may indicate an issue with the research or writing phase.</p>
        </div>
      )}

      {/* New Generation Button */}
      <div className="mt-8 text-center">
        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
        >
          <Sparkles className="w-5 h-5" />
          Generate New Content
        </button>
      </div>
    </div>
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
