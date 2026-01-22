'use client';

import {
  Search,
  CheckCircle,
  FileSearch,
  GitBranch,
  FileText,
  PenTool,
  BookOpen,
  Layers,
  RefreshCw,
  Loader2
} from 'lucide-react';

interface ProgressPanelProps {
  progress: Array<{
    node: string;
    phase: string;
    iteration: number;
    source_count: number;
    claim_count: number;
    chapter_count: number;
    word_count: number;
    messages: string[];
  }>;
}

const phaseConfig: Record<string, { icon: React.ElementType; label: string; description: string; color: string }> = {
  research: { icon: Search, label: 'Researching', description: 'Searching the web for relevant sources and information', color: 'text-blue-600' },
  verify: { icon: CheckCircle, label: 'Verifying Sources', description: 'Checking credibility and fetching content from sources', color: 'text-green-600' },
  extract: { icon: FileSearch, label: 'Extracting Claims', description: 'Pulling key facts and evidence from verified sources', color: 'text-purple-600' },
  cross_check: { icon: GitBranch, label: 'Cross-Checking', description: 'Verifying claims across multiple sources', color: 'text-orange-600' },
  synthesize: { icon: FileText, label: 'Creating Outline', description: 'Building chapter briefs from verified claims', color: 'text-cyan-600' },
  write: { icon: PenTool, label: 'Writing Content', description: 'Generating content for each chapter', color: 'text-pink-600' },
  summarize: { icon: BookOpen, label: 'Updating Memory', description: 'Maintaining coherence across chapters', color: 'text-indigo-600' },
  integrate: { icon: Layers, label: 'Integrating', description: 'Checking consistency and merging content', color: 'text-teal-600' },
  replan: { icon: RefreshCw, label: 'Analyzing Gaps', description: 'Identifying areas needing more research', color: 'text-amber-600' },
};

export function ProgressPanel({ progress }: ProgressPanelProps) {
  const latest = progress[progress.length - 1];
  const currentPhase = latest?.phase || 'research';
  const config = phaseConfig[currentPhase] || phaseConfig.research;
  const Icon = config.icon;

  const phases = Object.keys(phaseConfig);
  const currentIndex = phases.indexOf(currentPhase);

  return (
    <div className="max-w-4xl mx-auto">
      {/* Current Status */}
      <div className="bg-white rounded-xl border border-gray-200 p-8 shadow-sm mb-6">
        <div className="flex items-center justify-center mb-6">
          <div className={`p-4 rounded-full bg-gray-100 ${config.color}`}>
            <Icon className="w-8 h-8 animate-pulse" />
          </div>
        </div>
        <h2 className="text-2xl font-bold text-center text-gray-900 mb-2">
          {config.label}...
        </h2>
        <p className="text-center text-gray-500 text-sm mb-2">
          {config.description}
        </p>
        {latest?.messages[0] && (
          <p className="text-center text-gray-600 bg-gray-50 px-4 py-2 rounded-lg mt-3">
            {latest.messages[0]}
          </p>
        )}

        {/* Progress Bar */}
        <div className="mt-8">
          <div className="flex justify-between mb-2">
            {phases.map((phase, index) => {
              const PhaseIcon = phaseConfig[phase].icon;
              const isComplete = index < currentIndex;
              const isCurrent = index === currentIndex;
              return (
                <div
                  key={phase}
                  className={`flex flex-col items-center ${
                    isComplete ? 'text-green-600' : isCurrent ? config.color : 'text-gray-300'
                  }`}
                >
                  <PhaseIcon className="w-5 h-5" />
                </div>
              );
            })}
          </div>
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-500 transition-all duration-500"
              style={{ width: `${((currentIndex + 1) / phases.length) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Sources Found"
          value={latest?.source_count || 0}
          icon={Search}
        />
        <StatCard
          label="Claims Extracted"
          value={latest?.claim_count || 0}
          icon={FileSearch}
        />
        <StatCard
          label="Chapters Written"
          value={latest?.chapter_count || 0}
          icon={BookOpen}
        />
        <StatCard
          label="Words Written"
          value={latest?.word_count || 0}
          icon={PenTool}
        />
      </div>

      {/* Activity Log */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <h3 className="font-semibold text-gray-900 mb-4">Activity Log</h3>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {progress.slice().reverse().map((item, index) => (
            <div
              key={index}
              className="flex items-start gap-3 text-sm py-2 border-b border-gray-100 last:border-0"
            >
              <Loader2 className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
              <div>
                <span className="font-medium text-gray-700">
                  {phaseConfig[item.phase]?.label || item.phase}
                </span>
                {item.messages[0] && (
                  <p className="text-gray-500">{item.messages[0]}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-gray-500 mb-1">
        <Icon className="w-4 h-4" />
        <span className="text-sm">{label}</span>
      </div>
      <div className="text-2xl font-bold text-gray-900">
        {value.toLocaleString()}
      </div>
    </div>
  );
}
