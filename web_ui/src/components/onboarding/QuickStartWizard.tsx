'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  X,
  ArrowRight,
  ArrowLeft,
  Bot,
  GitBranch,
  MessageSquare,
  Slack,
  Github,
  Bell,
  Settings,
  Wrench,
  Layers,
  Zap,
  ChevronRight,
  Sparkles,
} from 'lucide-react';

interface QuickStartWizardProps {
  onClose: () => void;
  onRunAgent: () => void;
  onSkip: () => void;
}

const TOTAL_STEPS = 5;

export function QuickStartWizard({ onClose, onRunAgent, onSkip }: QuickStartWizardProps) {
  const [currentStep, setCurrentStep] = useState(1);

  const handleNext = () => {
    if (currentStep < TOTAL_STEPS) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleTryNow = () => {
    onRunAgent();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="relative bg-gradient-to-br from-orange-500 via-orange-600 to-amber-500 px-6 py-5 text-white">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-white/80 hover:text-white transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>

          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center backdrop-blur-sm">
              <span className="text-xl">🦊</span>
            </div>
            <div>
              <h1 className="text-xl font-bold">Quick Start Guide</h1>
              <p className="text-white/80 text-sm">Learn how IncidentFox works</p>
            </div>
          </div>

          {/* Progress dots */}
          <div className="flex items-center gap-2 mt-4">
            {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
              <button
                key={i}
                onClick={() => setCurrentStep(i + 1)}
                className={`w-2 h-2 rounded-full transition-all ${
                  i + 1 === currentStep
                    ? 'w-6 bg-white'
                    : i + 1 < currentStep
                    ? 'bg-white/80'
                    : 'bg-white/40'
                }`}
              />
            ))}
            <span className="ml-auto text-white/60 text-xs">
              Step {currentStep} of {TOTAL_STEPS}
            </span>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-6 min-h-[320px]">
          {currentStep === 1 && <StepWelcome />}
          {currentStep === 2 && <StepHowItWorks />}
          {currentStep === 3 && <StepConnectSystems />}
          {currentStep === 4 && <StepConfigureAgents />}
          {currentStep === 5 && <StepTryItNow />}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-800/50 flex items-center justify-between border-t border-gray-200 dark:border-gray-700">
          <div>
            {currentStep > 1 ? (
              <button
                onClick={handleBack}
                className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Back
              </button>
            ) : (
              <button
                onClick={onSkip}
                className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
              >
                Skip tutorial
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {currentStep < TOTAL_STEPS ? (
              <button
                onClick={handleNext}
                className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-medium transition-colors shadow-sm"
              >
                Next
                <ArrowRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleTryNow}
                className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-medium transition-colors shadow-sm"
              >
                <Sparkles className="w-4 h-4" />
                Try It Now
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Step 1: Welcome
function StepWelcome() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
          Welcome to IncidentFox
        </h2>
        <p className="text-gray-600 dark:text-gray-400">
          Your AI SRE that automatically investigates production incidents 24/7.
        </p>
      </div>

      <div className="bg-orange-50 dark:bg-orange-900/20 rounded-xl p-4 border border-orange-100 dark:border-orange-900/40">
        <p className="text-sm text-orange-800 dark:text-orange-200">
          When an incident fires, IncidentFox starts investigating immediately - analyzing logs,
          metrics, traces, and code changes to find the root cause before your team even opens their laptops.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <FeatureCard
          icon={<Zap className="w-5 h-5" />}
          title="Instant Response"
          description="Investigation starts in seconds"
        />
        <FeatureCard
          icon={<Layers className="w-5 h-5" />}
          title="Multi-Agent"
          description="Specialized AI for each system"
        />
        <FeatureCard
          icon={<MessageSquare className="w-5 h-5" />}
          title="Slack Native"
          description="Results where you work"
        />
      </div>
    </div>
  );
}

// Step 2: How It Works
function StepHowItWorks() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
          How Investigation Works
        </h2>
        <p className="text-gray-600 dark:text-gray-400">
          IncidentFox uses a team of specialized AI agents that work together.
        </p>
      </div>

      {/* Agent topology diagram */}
      <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-5">
        <div className="flex flex-col items-center">
          {/* Planner */}
          <div className="flex items-center gap-2 px-4 py-2 bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 rounded-lg font-medium text-sm">
            <Bot className="w-4 h-4" />
            Planner Agent
          </div>

          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600" />
          <div className="text-xs text-gray-400">delegates to</div>
          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600" />

          {/* Investigation Agent */}
          <div className="flex items-center gap-2 px-4 py-2 bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 rounded-lg font-medium text-sm">
            <Bot className="w-4 h-4" />
            Investigation Agent
          </div>

          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600" />
          <div className="text-xs text-gray-400">coordinates</div>
          <div className="flex items-center gap-1 mt-2">
            <div className="w-8 h-px bg-gray-300 dark:bg-gray-600" />
            <div className="w-8 h-px bg-gray-300 dark:bg-gray-600" />
            <div className="w-8 h-px bg-gray-300 dark:bg-gray-600" />
          </div>

          {/* Sub-agents */}
          <div className="flex flex-wrap justify-center gap-2 mt-3">
            <SubAgentChip label="K8s" />
            <SubAgentChip label="AWS" />
            <SubAgentChip label="Metrics" />
            <SubAgentChip label="Logs" />
            <SubAgentChip label="GitHub" />
          </div>
        </div>
      </div>

      <div className="text-sm text-gray-600 dark:text-gray-400 space-y-2">
        <p>
          <strong className="text-gray-900 dark:text-white">1.</strong> The Planner receives your incident and determines the investigation strategy
        </p>
        <p>
          <strong className="text-gray-900 dark:text-white">2.</strong> Specialized agents query Kubernetes, AWS, Grafana, logs, and code changes
        </p>
        <p>
          <strong className="text-gray-900 dark:text-white">3.</strong> Findings are synthesized into root cause analysis with recommendations
        </p>
      </div>
    </div>
  );
}

// Step 3: Connect Systems
function StepConnectSystems() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
          Connect Your Systems
        </h2>
        <p className="text-gray-600 dark:text-gray-400">
          Most investigations are triggered automatically via webhooks - no human action needed.
        </p>
      </div>

      <div className="space-y-3">
        <IntegrationItem
          icon={<Slack className="w-5 h-5" />}
          name="Slack"
          description="@incidentfox investigate checkout errors"
          badge="Primary"
          badgeColor="bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
        />
        <IntegrationItem
          icon={<Bell className="w-5 h-5" />}
          name="PagerDuty / Incident.io"
          description="Auto-triggered when incidents are created"
        />
        <IntegrationItem
          icon={<Github className="w-5 h-5" />}
          name="GitHub"
          description="Comment @incidentfox on PRs or issues"
        />
      </div>

      <div className="bg-blue-50 dark:bg-blue-900/20 rounded-xl p-4 border border-blue-100 dark:border-blue-900/40">
        <p className="text-sm text-blue-800 dark:text-blue-200">
          <strong>Tip:</strong> Start with Slack integration - it&apos;s the most common way teams use IncidentFox.
          Once connected, just @mention the bot in any channel.
        </p>
      </div>

      <Link
        href="/team/tools"
        className="flex items-center justify-between w-full px-4 py-3 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors group"
      >
        <div className="flex items-center gap-3">
          <Settings className="w-5 h-5 text-gray-500" />
          <span className="font-medium text-gray-900 dark:text-white">Set Up Integrations</span>
        </div>
        <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition-colors" />
      </Link>
    </div>
  );
}

// Step 4: Configure Agents
function StepConfigureAgents() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
          Configure Your Agents
        </h2>
        <p className="text-gray-600 dark:text-gray-400">
          Customize how agents investigate to match your infrastructure.
        </p>
      </div>

      <div className="space-y-4">
        <ConfigSection
          icon={<Wrench className="w-5 h-5" />}
          title="Integrations & Tools"
          description="Connect Grafana, Datadog, AWS, Kubernetes to unlock investigation capabilities. More integrations = better investigations."
        />
        <ConfigSection
          icon={<MessageSquare className="w-5 h-5" />}
          title="Agent Prompts"
          description='Add team context to system prompts: "We use EKS on AWS, primary services are checkout-service and payment-service..."'
        />
        <ConfigSection
          icon={<Bot className="w-5 h-5" />}
          title="Enable/Disable Agents"
          description="Turn off agents you don't need (e.g., disable AWS agent if you're on GCP). Add MCP servers for custom tools."
        />
      </div>

      <div className="flex gap-3">
        <Link
          href="/team/tools"
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors text-sm font-medium text-gray-700 dark:text-gray-300"
        >
          <Wrench className="w-4 h-4" />
          Integrations
        </Link>
        <Link
          href="/team/agents"
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors text-sm font-medium text-gray-700 dark:text-gray-300"
        >
          <Bot className="w-4 h-4" />
          Agent Config
        </Link>
      </div>
    </div>
  );
}

// Step 5: Try It Now
function StepTryItNow() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
          Try It Now
        </h2>
        <p className="text-gray-600 dark:text-gray-400">
          Test the agent before deploying to Slack. Describe an incident and watch it investigate.
        </p>
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Example prompts:</p>
        <div className="space-y-2">
          <ExamplePrompt text="My checkout API is returning 500 errors since 10am" />
          <ExamplePrompt text="Memory usage spiking on payment-service pods" />
          <ExamplePrompt text="CI pipeline failing on main branch after recent merge" />
        </div>
      </div>

      <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl p-4 border border-amber-100 dark:border-amber-900/40">
        <p className="text-sm text-amber-800 dark:text-amber-200">
          <strong>Note:</strong> Investigation quality depends on your configured integrations.
          Without Grafana/K8s/AWS connected, the agent can reason but can&apos;t query real systems.
        </p>
      </div>

      <div className="text-center pt-2">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Click <strong>&quot;Try It Now&quot;</strong> below to open the investigation interface
        </p>
      </div>
    </div>
  );
}

// Helper components
function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="text-center p-3 rounded-xl bg-gray-50 dark:bg-gray-800">
      <div className="w-10 h-10 mx-auto mb-2 rounded-lg bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 flex items-center justify-center">
        {icon}
      </div>
      <h3 className="font-medium text-gray-900 dark:text-white text-sm">{title}</h3>
      <p className="text-gray-500 dark:text-gray-400 text-xs mt-1">{description}</p>
    </div>
  );
}

function SubAgentChip({ label }: { label: string }) {
  return (
    <span className="px-3 py-1 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-full text-xs font-medium">
      {label}
    </span>
  );
}

function IntegrationItem({
  icon,
  name,
  description,
  badge,
  badgeColor
}: {
  icon: React.ReactNode;
  name: string;
  description: string;
  badge?: string;
  badgeColor?: string;
}) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-800">
      <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 flex items-center justify-center">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-gray-900 dark:text-white text-sm">{name}</h3>
          {badge && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${badgeColor}`}>
              {badge}
            </span>
          )}
        </div>
        <p className="text-gray-500 dark:text-gray-400 text-xs mt-0.5 font-mono">{description}</p>
      </div>
    </div>
  );
}

function ConfigSection({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 flex items-center justify-center">
        {icon}
      </div>
      <div>
        <h3 className="font-medium text-gray-900 dark:text-white text-sm">{title}</h3>
        <p className="text-gray-500 dark:text-gray-400 text-xs mt-0.5">{description}</p>
      </div>
    </div>
  );
}

function ExamplePrompt({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-gray-100 dark:bg-gray-800 rounded-lg">
      <GitBranch className="w-4 h-4 text-gray-400 flex-shrink-0" />
      <span className="text-sm text-gray-700 dark:text-gray-300">{text}</span>
    </div>
  );
}
