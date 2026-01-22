'use client';

import { useState } from 'react';
import { GenerationForm } from '@/components/GenerationForm';
import { ProgressPanel } from '@/components/ProgressPanel';
import { ResultsPanel } from '@/components/ResultsPanel';
import { BookOpen, Sparkles } from 'lucide-react';

export type GenerationStatus = 'idle' | 'generating' | 'complete' | 'error';

export interface GenerationProgress {
  node: string;
  phase: string;
  iteration: number;
  source_count: number;
  claim_count: number;
  chapter_count: number;
  word_count: number;
  messages: string[];
}

export interface GenerationResult {
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
  warnings: string[];
}

export default function Home() {
  const [status, setStatus] = useState<GenerationStatus>('idle');
  const [progress, setProgress] = useState<GenerationProgress[]>([]);
  const [result, setResult] = useState<GenerationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async (formData: {
    topic: string;
    subtopics: string[];
    target_word_count: number;
    depth: string;
    style_tone: string;
  }) => {
    setStatus('generating');
    setProgress([]);
    setResult(null);
    setError(null);

    try {
      // Call backend directly to avoid Next.js proxy buffering SSE
      const response = await fetch('http://localhost:8000/api/v1/generation/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.status === 'complete' && data.content) {
                setResult(data);
                setStatus('complete');
              } else if (data.status === 'error') {
                setError(data.error);
                setStatus('error');
              } else if (data.node) {
                setProgress(prev => [...prev, data]);
              }
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setStatus('error');
    }
  };

  const handleReset = () => {
    setStatus('idle');
    setProgress([]);
    setResult(null);
    setError(null);
  };

  return (
    <main className="min-h-screen">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="bg-primary-500 p-2 rounded-lg">
                <BookOpen className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Prolific</h1>
                <p className="text-sm text-gray-500">AI Content Generation</p>
              </div>
            </div>
            {status !== 'idle' && (
              <button
                onClick={handleReset}
                className="text-sm text-gray-600 hover:text-gray-900 flex items-center gap-1"
              >
                <Sparkles className="w-4 h-4" />
                New Generation
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {status === 'idle' && (
          <GenerationForm onSubmit={handleGenerate} />
        )}

        {status === 'generating' && (
          <ProgressPanel progress={progress} />
        )}

        {status === 'complete' && result && (
          <ResultsPanel result={result} onReset={handleReset} />
        )}

        {status === 'error' && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <h2 className="text-lg font-semibold text-red-800 mb-2">Generation Failed</h2>
            <p className="text-red-600 mb-4">{error}</p>
            <button
              onClick={handleReset}
              className="bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
