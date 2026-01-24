'use client';

import { useEffect, useState } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import {
  LayoutTemplate,
  Search,
  Star,
  Users,
  Loader2,
  Home,
  XCircle,
  Sparkles,
  CheckCircle2,
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

export default function AdminTemplatesPage() {
  const { identity } = useIdentity();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateDetail | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [applying, setApplying] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Load templates
  useEffect(() => {
    loadTemplates();
  }, [selectedCategory, searchQuery]);

  const loadTemplates = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedCategory) params.set('category', selectedCategory);
      if (searchQuery) params.set('search', searchQuery);

      const res = await apiFetch(`/api/admin/templates?${params.toString()}`);
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

  const handlePreview = async (templateId: string) => {
    try {
      const res = await apiFetch(`/api/admin/templates/${templateId}`);
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
    if (!confirm('Apply this template to your organization? This will update the org-level agent configuration that all teams inherit from.')) {
      return;
    }

    setApplying(true);
    setMessage(null);

    try {
      const res = await apiFetch(`/api/admin/templates/${templateId}/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      const data = await res.json();

      if (res.ok) {
        setMessage({
          type: 'success',
          text: `Template applied successfully to organization! All teams will inherit this configuration.`,
        });
        setShowPreview(false);
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

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <div className="bg-slate-900 border-b border-slate-800">
        <div className="p-6">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-slate-400 mb-4">
            <button
              onClick={() => (window.location.href = '/admin')}
              className="hover:text-slate-200 transition-colors flex items-center gap-1"
            >
              <Home className="w-4 h-4" />
              Admin Dashboard
            </button>
            <span>/</span>
            <span className="text-slate-200">Templates</span>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-white flex items-center gap-3">
                <LayoutTemplate className="w-8 h-8 text-cyan-400" />
                Template Marketplace
              </h1>
              <p className="text-slate-400 mt-2">
                Browse pre-configured agent systems optimized for specific use cases
              </p>
            </div>
          </div>

          {/* Filters */}
          <div className="flex gap-4 mt-6">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-slate-400" />
              <input
                type="text"
                placeholder="Search templates..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-slate-700 rounded-lg bg-slate-800 text-white placeholder-slate-500"
              />
            </div>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="px-4 py-2 border border-slate-700 rounded-lg bg-slate-800 text-white"
            >
              {CATEGORIES.map((cat) => (
                <option key={cat.value} value={cat.value}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>

          {/* Message */}
          {message && (
            <div
              className={`mt-4 p-4 rounded-lg border flex items-start gap-3 ${
                message.type === 'success'
                  ? 'bg-green-900/20 border-green-800'
                  : 'bg-red-900/20 border-red-800'
              }`}
            >
              {message.type === 'success' ? (
                <CheckCircle2 className="w-5 h-5 text-green-400 mt-0.5" />
              ) : (
                <XCircle className="w-5 h-5 text-red-400 mt-0.5" />
              )}
              <p
                className={`text-sm ${
                  message.type === 'success' ? 'text-green-100' : 'text-red-100'
                }`}
              >
                {message.text}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Templates Grid */}
      <div className="p-6">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
          </div>
        ) : templates.length === 0 ? (
          <div className="text-center py-12">
            <LayoutTemplate className="w-16 h-16 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-400">No templates found</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {templates.map((template) => (
              <div
                key={template.id}
                onClick={() => handlePreview(template.id)}
                className="bg-slate-900 border border-slate-800 rounded-lg p-6 hover:border-slate-700 hover:shadow-lg transition-all cursor-pointer"
              >
                {/* Category Badge */}
                <div className="flex items-center justify-between mb-4">
                  <span className="text-2xl">{CATEGORY_ICONS[template.category] || '📦'}</span>
                  <span className="text-xs px-2 py-1 bg-slate-800 text-slate-400 rounded">
                    {template.category}
                  </span>
                </div>

                {/* Title */}
                <h3 className="text-lg font-semibold text-white mb-2">
                  {template.name}
                </h3>

                {/* Description */}
                <p className="text-sm text-slate-400 mb-4 line-clamp-3">
                  {template.description}
                </p>

                {/* Stats */}
                <div className="flex items-center gap-4 text-xs text-slate-500 mb-4">
                  <div className="flex items-center gap-1">
                    <Users className="w-4 h-4" />
                    {template.usage_count} teams
                  </div>
                  {template.avg_rating && (
                    <div className="flex items-center gap-1">
                      <Star className="w-4 h-4 fill-yellow-500 text-yellow-500" />
                      {template.avg_rating.toFixed(1)}
                    </div>
                  )}
                  <div className="ml-auto text-slate-600">
                    v{template.version}
                  </div>
                </div>

                {/* Required MCPs */}
                {template.required_mcps.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {template.required_mcps.slice(0, 3).map((mcp) => (
                      <span
                        key={mcp}
                        className="text-xs px-2 py-1 bg-cyan-900/30 text-cyan-400 rounded"
                      >
                        {mcp}
                      </span>
                    ))}
                    {template.required_mcps.length > 3 && (
                      <span className="text-xs px-2 py-1 bg-slate-800 text-slate-400 rounded">
                        +{template.required_mcps.length - 3} more
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Preview Modal */}
      {showPreview && selectedTemplate && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="p-6 border-b border-slate-800 sticky top-0 bg-slate-900 z-10">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <span className="text-4xl">
                    {CATEGORY_ICONS[selectedTemplate.category] || '📦'}
                  </span>
                  <div>
                    <h2 className="text-2xl font-bold text-white">
                      {selectedTemplate.name}
                    </h2>
                    <p className="text-sm text-slate-400 mt-1">
                      {selectedTemplate.category} • v{selectedTemplate.version}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setShowPreview(false)}
                  className="text-slate-400 hover:text-slate-200 transition-colors"
                >
                  <XCircle className="w-6 h-6" />
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="p-6 space-y-6">
              {/* Description */}
              <div>
                <h3 className="text-sm font-semibold text-white mb-2">
                  Description
                </h3>
                <p className="text-slate-300">
                  {selectedTemplate.description}
                </p>
                {selectedTemplate.detailed_description && (
                  <p className="text-slate-400 mt-2">
                    {selectedTemplate.detailed_description}
                  </p>
                )}
              </div>

              {/* Example Scenarios */}
              {selectedTemplate.example_scenarios.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-white mb-2">
                    Example Scenarios
                  </h3>
                  <ul className="list-disc list-inside space-y-1">
                    {selectedTemplate.example_scenarios.map((scenario, idx) => (
                      <li key={idx} className="text-slate-300">
                        {scenario}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Required Integrations */}
              <div>
                <h3 className="text-sm font-semibold text-white mb-2">
                  Required Integrations
                </h3>
                {selectedTemplate.required_mcps.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedTemplate.required_mcps.map((mcp) => (
                      <span
                        key={mcp}
                        className="px-3 py-1 bg-cyan-900/30 text-cyan-400 rounded-lg text-sm border border-cyan-800/50"
                      >
                        {mcp}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-slate-400 text-sm">No integrations required</p>
                )}
              </div>

              {/* Agents */}
              <div>
                <h3 className="text-sm font-semibold text-white mb-2">
                  Agents Included
                </h3>
                <div className="space-y-2">
                  {Object.keys(selectedTemplate.template_json.agents || {}).map((agentKey) => {
                    const agent = selectedTemplate.template_json.agents[agentKey];
                    return (
                      <div
                        key={agentKey}
                        className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/50"
                      >
                        <p className="font-medium text-white">
                          {agent.name}
                        </p>
                        {agent.description && (
                          <p className="text-xs text-slate-400 mt-1">
                            {agent.description}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Stats */}
              <div className="flex items-center gap-6 text-sm text-slate-400 pt-4 border-t border-slate-800">
                <div className="flex items-center gap-2">
                  <Users className="w-5 h-5" />
                  <span>{selectedTemplate.usage_count} teams using this</span>
                </div>
                {selectedTemplate.avg_rating && (
                  <div className="flex items-center gap-2">
                    <Star className="w-5 h-5 fill-yellow-500 text-yellow-500" />
                    <span>{selectedTemplate.avg_rating.toFixed(1)} rating</span>
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-slate-800 flex justify-between items-center sticky bottom-0 bg-slate-900">
              <div className="text-sm text-slate-400">
                <p className="font-medium text-slate-300 mb-1">Apply to Organization</p>
                <p className="text-xs">All teams will inherit this agent configuration</p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowPreview(false)}
                  className="px-4 py-2 text-slate-300 hover:bg-slate-800 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleApply(selectedTemplate.id)}
                  disabled={applying}
                  className="px-6 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {applying ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Applying...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Apply to Organization
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
