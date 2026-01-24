'use client';

import { useState } from 'react';
import { X, Zap, Brain, Shield, ArrowRight } from 'lucide-react';

interface WelcomeModalProps {
  role: 'admin' | 'team';
  onClose: () => void;
  onRunAgent: () => void;
  onSkip: () => void;
}

export function WelcomeModal({ role, onClose, onRunAgent, onSkip }: WelcomeModalProps) {
  const isAdmin = role === 'admin';

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        {/* Header with gradient */}
        <div className="relative bg-gradient-to-br from-orange-500 via-orange-600 to-amber-500 px-6 py-8 text-white">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-white/80 hover:text-white transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>

          {/* Logo/Icon */}
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-xl bg-white/20 flex items-center justify-center backdrop-blur-sm">
              <span className="text-2xl">🦊</span>
            </div>
            <div>
              <h1 className="text-2xl font-bold">Welcome to IncidentFox</h1>
              <p className="text-white/80 text-sm">Your AI incident investigation assistant</p>
            </div>
          </div>

          <p className="text-white/90 text-sm leading-relaxed">
            {isAdmin
              ? 'As an admin, you can configure organization settings, manage teams, and oversee incident response across your organization.'
              : 'IncidentFox helps you investigate incidents faster by automatically analyzing logs, metrics, and traces using AI agents.'}
          </p>
        </div>

        {/* Features */}
        <div className="px-6 py-5 space-y-4">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            What you can do
          </h2>

          <div className="space-y-3">
            <FeatureItem
              icon={<Zap className="w-5 h-5" />}
              title="Run AI Agents"
              description="Describe an incident and let AI investigate automatically"
            />
            <FeatureItem
              icon={<Brain className="w-5 h-5" />}
              title="Knowledge Base"
              description="Upload runbooks and documentation for smarter investigations"
            />
            <FeatureItem
              icon={<Shield className="w-5 h-5" />}
              title="Integrations"
              description="Connect Grafana, Kubernetes, and other tools"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-800/50 flex items-center justify-between">
          <button
            onClick={onSkip}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            Skip for now
          </button>

          <button
            onClick={onRunAgent}
            className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-medium transition-colors shadow-sm"
          >
            Run Your First Agent
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function FeatureItem({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 flex items-center justify-center">
        {icon}
      </div>
      <div>
        <h3 className="font-medium text-gray-900 dark:text-white text-sm">{title}</h3>
        <p className="text-gray-500 dark:text-gray-400 text-xs">{description}</p>
      </div>
    </div>
  );
}
