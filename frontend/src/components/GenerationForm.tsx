'use client';

import { useState } from 'react';
import {
  Sparkles,
  BookOpen,
  FileText,
  Settings,
  Plus,
  X,
  ChevronDown
} from 'lucide-react';

interface GenerationFormProps {
  onSubmit: (data: {
    topic: string;
    subtopics: string[];
    target_word_count: number;
    depth: string;
    style_tone: string;
  }) => void;
}

export function GenerationForm({ onSubmit }: GenerationFormProps) {
  const [topic, setTopic] = useState('');
  const [subtopics, setSubtopics] = useState<string[]>([]);
  const [newSubtopic, setNewSubtopic] = useState('');
  const [wordCount, setWordCount] = useState(5000);
  const [depth, setDepth] = useState('standard');
  const [styleTone, setStyleTone] = useState('academic');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const addSubtopic = () => {
    if (newSubtopic.trim()) {
      setSubtopics([...subtopics, newSubtopic.trim()]);
      setNewSubtopic('');
    }
  };

  const removeSubtopic = (index: number) => {
    setSubtopics(subtopics.filter((_, i) => i !== index));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      topic,
      subtopics,
      target_word_count: wordCount,
      depth,
      style_tone: styleTone,
    });
  };

  const wordCountPresets = [
    { label: 'Article', value: 2000, pages: '4-5' },
    { label: 'Guide', value: 5000, pages: '10-12' },
    { label: 'White Paper', value: 15000, pages: '30-35' },
    { label: 'Short Book', value: 50000, pages: '100-120' },
  ];

  return (
    <div className="max-w-3xl mx-auto">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-100 rounded-2xl mb-4">
          <Sparkles className="w-8 h-8 text-primary-600" />
        </div>
        <h2 className="text-3xl font-bold text-gray-900 mb-2">
          Create Something Amazing
        </h2>
        <p className="text-gray-600">
          Enter a topic and let AI research and write comprehensive content for you
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Topic Input */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            <BookOpen className="w-4 h-4 inline mr-2" />
            What do you want to write about?
          </label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g., The History of Artificial Intelligence"
            className="w-full px-4 py-3 text-lg border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            required
          />
        </div>

        {/* Subtopics */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            <FileText className="w-4 h-4 inline mr-2" />
            Subtopics to cover (optional)
          </label>
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newSubtopic}
              onChange={(e) => setNewSubtopic(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addSubtopic())}
              placeholder="Add a subtopic..."
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
            <button
              type="button"
              onClick={addSubtopic}
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
            >
              <Plus className="w-5 h-5" />
            </button>
          </div>
          {subtopics.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {subtopics.map((subtopic, index) => (
                <span
                  key={index}
                  className="inline-flex items-center gap-1 px-3 py-1 bg-primary-100 text-primary-700 rounded-full text-sm"
                >
                  {subtopic}
                  <button
                    type="button"
                    onClick={() => removeSubtopic(index)}
                    className="hover:text-primary-900"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Word Count */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <label className="block text-sm font-medium text-gray-700 mb-3">
            Content Length
          </label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            {wordCountPresets.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => setWordCount(preset.value)}
                className={`p-3 rounded-lg border-2 text-center transition-all ${
                  wordCount === preset.value
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <div className="font-medium text-gray-900">{preset.label}</div>
                <div className="text-sm text-gray-500">~{preset.pages} pages</div>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min="1000"
              max="100000"
              step="1000"
              value={wordCount}
              onChange={(e) => setWordCount(Number(e.target.value))}
              className="flex-1"
            />
            <div className="w-32 text-right">
              <span className="text-2xl font-bold text-gray-900">
                {(wordCount / 1000).toFixed(0)}k
              </span>
              <span className="text-gray-500 ml-1">words</span>
            </div>
          </div>
        </div>

        {/* Advanced Settings */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-gray-50"
          >
            <span className="flex items-center gap-2 font-medium text-gray-700">
              <Settings className="w-4 h-4" />
              Advanced Settings
            </span>
            <ChevronDown
              className={`w-5 h-5 text-gray-400 transition-transform ${
                showAdvanced ? 'rotate-180' : ''
              }`}
            />
          </button>
          {showAdvanced && (
            <div className="px-6 pb-6 border-t border-gray-100 pt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Research Depth
                </label>
                <select
                  value={depth}
                  onChange={(e) => setDepth(e.target.value)}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                >
                  <option value="overview">Overview - Quick summary</option>
                  <option value="standard">Standard - Balanced coverage</option>
                  <option value="deep">Deep - Thorough analysis</option>
                  <option value="exhaustive">Exhaustive - Comprehensive research</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Writing Style
                </label>
                <select
                  value={styleTone}
                  onChange={(e) => setStyleTone(e.target.value)}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                >
                  <option value="academic">Academic - Formal, scholarly</option>
                  <option value="conversational">Conversational - Friendly, engaging</option>
                  <option value="technical">Technical - Precise, detailed</option>
                  <option value="journalistic">Journalistic - News-style reporting</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={!topic.trim()}
          className="w-full py-4 bg-primary-600 text-white text-lg font-semibold rounded-xl hover:bg-primary-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          <Sparkles className="w-5 h-5" />
          Generate Content
        </button>

        <p className="text-center text-sm text-gray-500">
          Estimated cost: ${((wordCount / 50000) * 10).toFixed(2)} - ${((wordCount / 50000) * 15).toFixed(2)}
        </p>
      </form>
    </div>
  );
}
