'use client';

import { useEffect, useState } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import {
  LayoutTemplate,
  Search,
  Filter,
  Star,
  Users,
  CheckCircle2,
  XCircle,
  Loader2,
  ExternalLink,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import { apiFetch } from '@/lib/apiClient';

interface Template {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  icon_url?: string;
  example_scenarios: string[];
  required_mcps: string[];
  usage_count: number;
  avg_rating?: number;
  version: string;
}

interface TemplateDetail extends Template {
  detailed_description?: string;
  template_json: any;
  demo_video_url?: string;
  required_tools: string[];
}

interface CurrentTemplate {
  id: string;
  template_id: string;
  template_name: string;
  applied_at: string;
  template_version: string;
  has_customizations: boolean;
}

const CATEGORIES = [
  { value: '', label: 'All Categories' },
  { value: 'incident-response', label: 'Incident Response' },
  { value: 'ci-cd', label: 'CI/CD' },
  { value: 'finops', label: 'FinOps' },
  { value: 'coding', label: 'Coding' },
  { value: 'data', label: 'Data' },
  { value: 'observability', label: 'Observability' },
  { value: 'reliability', label: 'Reliability' },
  { value: 'demo', label: 'Demo' },
];

const CATEGORY_ICONS: Record<string, string> = {
  'incident-response': '🚨',
  'ci-cd': '🔧',
  'finops': '💰',
  'coding': '💻',
  'data': '🗄️',
  'observability': '📊',
  'reliability': '🛡️',
  'demo': '🎉',
};

export default function TemplatesPage() {
  const { identity } = useIdentity();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateDetail | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [applying, setApplying] = useState(false);
  const [currentTemplate, setCurrentTemplate] = useState<CurrentTemplate | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Load templates
  useEffect(() => {
    loadTemplates();
    loadCurrentTemplate();
  }, [selectedCategory, searchQuery]);

  const loadTemplates = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedCategory) params.set('category', selectedCategory);
      if (searchQuery) params.set('search', searchQuery);

      const res = await apiFetch(`/api/team/templates?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setTemplates(data.templates || []);
      }
    } catch (e) {
      console.error('Failed to load templates:', e);
    } finally {
      setLoading(false);
    }
  };

  const loadCurrentTemplate = async () => {
    try {
      const res = await apiFetch('/api/team/templates/current');
      if (res.ok) {
        const data = await res.json();
        setCurrentTemplate(data.application || null);
      }
    } catch (e) {
      console.error('Failed to load current template:', e);
    }
  };

  const handlePreview = async (templateId: string) => {
    try {
      const res = await apiFetch(`/api/team/templates/${templateId}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedTemplate(data);
        setShowPreview(true);
      }
    } catch (e) {
      console.error('Failed to load template details:', e);
    }
  };

  const handleApply = async (templateId: string) => {
    if (!confirm('Apply this template to your team? This will update your agent configuration.')) {
      return;
    }

    setApplying(true);
    setMessage(null);

    try {
      const res = await apiFetch(`/api/team/templates/${templateId}/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customize: {} }),
      });

      const data = await res.json();

      if (res.ok) {
        setMessage({
          type: 'success',
          text: `Template applied successfully! ${data.message || ''}`,
        });
        setShowPreview(false);
        loadCurrentTemplate();
        // Reload page after 2 seconds to show updated config
        setTimeout(() => window.location.reload(), 2000);
      } else {
        setMessage({
          type: 'error',
          text: data.error || 'Failed to apply template',
        });
      }
    } catch (e: any) {
      setMessage({
        type: 'error',
        text: e?.message || 'Failed to apply template',
      });
    } finally {
      setApplying(false);
    }
  };

  const filteredTemplates = templates;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
              <LayoutTemplate className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
                Template Marketplace
              </h1>
              <p className="text-gray-600 dark:text-gray-400">
                Pre-configured agent systems optimized for specific use cases
              </p>
            </div>
          </div>
        </div>

        {/* Current Template Badge */}
        {currentTemplate && (
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-green-900 dark:text-green-100">
                Current Template: {currentTemplate.template_name}
              </p>
              <p className="text-xs text-green-700 dark:text-green-300 mt-1">
                Applied on {new Date(currentTemplate.applied_at).toLocaleDateString()}
                {currentTemplate.has_customizations && ' • Customized'}
              </p>
            </div>
          </div>
        )}

        {/* Message */}
        {message && (
          <div
            className={`mt-4 p-4 rounded-lg border flex items-start gap-3 ${
              message.type === 'success'
                ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
            }`}
          >
            {message.type === 'success' ? (
              <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400 mt-0.5" />
            ) : (
              <XCircle className="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5" />
            )}
            <p
              className={`text-sm ${
                message.type === 'success'
                  ? 'text-green-900 dark:text-green-100'
                  : 'text-red-900 dark:text-red-100'
              }`}
            >
              {message.text}
            </p>
          </div>
        )}

        {/* Filters */}
        <div className="flex gap-4 mt-6">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search templates..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            />
          </div>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="px-4 py-2 border border-gray-300 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          >
            {CATEGORIES.map((cat) => (
              <option key={cat.value} value={cat.value}>
                {cat.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Templates Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="text-center py-12">
          <LayoutTemplate className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-600 dark:text-gray-400">No templates found</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredTemplates.map((template) => (
            <div
              key={template.id}
              className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6 hover:shadow-lg transition-shadow cursor-pointer"
              onClick={() => handlePreview(template.id)}
            >
              {/* Category Badge */}
              <div className="flex items-center justify-between mb-4">
                <span className="text-2xl">{CATEGORY_ICONS[template.category] || '📦'}</span>
                <span className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded">
                  {template.category}
                </span>
              </div>

              {/* Title */}
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                {template.name}
              </h3>

              {/* Description */}
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4 line-clamp-3">
                {template.description}
              </p>

              {/* Stats */}
              <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400 mb-4">
                <div className="flex items-center gap-1">
                  <Users className="w-4 h-4" />
                  {template.usage_count}
                </div>
                {template.avg_rating && (
                  <div className="flex items-center gap-1">
                    <Star className="w-4 h-4 fill-yellow-400 text-yellow-400" />
                    {template.avg_rating.toFixed(1)}
                  </div>
                )}
              </div>

              {/* Required MCPs */}
              <div className="flex flex-wrap gap-2">
                {template.required_mcps.slice(0, 3).map((mcp) => (
                  <span
                    key={mcp}
                    className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded"
                  >
                    {mcp}
                  </span>
                ))}
                {template.required_mcps.length > 3 && (
                  <span className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded">
                    +{template.required_mcps.length - 3} more
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Preview Modal */}
      {showPreview && selectedTemplate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="p-6 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <span className="text-4xl">
                    {CATEGORY_ICONS[selectedTemplate.category] || '📦'}
                  </span>
                  <div>
                    <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                      {selectedTemplate.name}
                    </h2>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                      {selectedTemplate.category} • v{selectedTemplate.version}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setShowPreview(false)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                >
                  <XCircle className="w-6 h-6" />
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="p-6 space-y-6">
              {/* Description */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                  Description
                </h3>
                <p className="text-gray-600 dark:text-gray-400">
                  {selectedTemplate.description}
                </p>
              </div>

              {/* Example Scenarios */}
              {selectedTemplate.example_scenarios.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                    Example Scenarios
                  </h3>
                  <ul className="list-disc list-inside space-y-1">
                    {selectedTemplate.example_scenarios.map((scenario, idx) => (
                      <li key={idx} className="text-gray-600 dark:text-gray-400">
                        {scenario}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Required Integrations */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                  Required Integrations
                </h3>
                <div className="flex flex-wrap gap-2">
                  {selectedTemplate.required_mcps.map((mcp) => (
                    <span
                      key={mcp}
                      className="px-3 py-1 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded-lg text-sm"
                    >
                      {mcp}
                    </span>
                  ))}
                </div>
              </div>

              {/* Agents */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                  Agents Included
                </h3>
                <div className="space-y-2">
                  {Object.keys(selectedTemplate.template_json.agents || {}).map((agentKey) => {
                    const agent = selectedTemplate.template_json.agents[agentKey];
                    return (
                      <div
                        key={agentKey}
                        className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg"
                      >
                        <p className="font-medium text-gray-900 dark:text-white">
                          {agent.name}
                        </p>
                        <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                          {agent.description}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Stats */}
              <div className="flex items-center gap-6 text-sm text-gray-600 dark:text-gray-400">
                <div className="flex items-center gap-2">
                  <Users className="w-5 h-5" />
                  <span>{selectedTemplate.usage_count} teams using this</span>
                </div>
                {selectedTemplate.avg_rating && (
                  <div className="flex items-center gap-2">
                    <Star className="w-5 h-5 fill-yellow-400 text-yellow-400" />
                    <span>{selectedTemplate.avg_rating.toFixed(1)} rating</span>
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
              <button
                onClick={() => setShowPreview(false)}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleApply(selectedTemplate.id)}
                disabled={applying}
                className="px-6 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {applying ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Applying...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Apply to My Team
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
