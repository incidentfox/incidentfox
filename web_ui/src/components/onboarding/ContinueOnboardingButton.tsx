'use client';

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useOnboarding, type Step4NextAction, type Step4Progress } from '@/lib/useOnboarding';
import { ArrowRight, X } from 'lucide-react';

interface ContinueOnboardingButtonProps {
  onContinue: (step: number, step4Action?: Step4NextAction) => void;
  /** When true, uses localStorage only for onboarding state (for visitors) */
  isVisitor?: boolean;
}

const STEP_NAMES: { [key: number]: string } = {
  1: 'Welcome',
  2: 'How It Works',
  3: 'Connect Systems',
  4: 'Configure Agents',
  5: 'Try It Now',
  6: 'Complete',
};

const DEFAULT_STEP4_PROGRESS: Step4Progress = {
  visitedIntegrations: false,
  visitedAgentConfig: false,
};

export function ContinueOnboardingButton({ onContinue, isVisitor = false }: ContinueOnboardingButtonProps) {
  const pathname = usePathname();
  const { clearQuickStartStep } = useOnboarding({ isVisitor });
  const [dismissed, setDismissed] = useState(false);
  const [localStep, setLocalStep] = useState<number | null>(null);
  const [localStep4Progress, setLocalStep4Progress] = useState<Step4Progress>(DEFAULT_STEP4_PROGRESS);
  const [wasCompleted, setWasCompleted] = useState(false);

  // Check localStorage for state - runs on mount AND on navigation
  useEffect(() => {
    try {
      const cached = localStorage.getItem('incidentfox_onboarding');
      if (cached) {
        const data = JSON.parse(cached);
        const step = data.quickStartStep ?? null;
        setLocalStep(step);
        setLocalStep4Progress(data.step4Progress ?? DEFAULT_STEP4_PROGRESS);
        // Set states based on whether step is null
        if (step === null) {
          setWasCompleted(true);
        } else {
          // Reset dismissed and wasCompleted if there's an active step
          setDismissed(false);
          setWasCompleted(false);
        }
      }
    } catch {
      // Ignore parse errors
    }
  }, [pathname]); // Re-run when pathname changes (navigation)

  // Listen for state changes (from other hook instances)
  useEffect(() => {
    const checkLocalStorage = () => {
      try {
        const cached = localStorage.getItem('incidentfox_onboarding');
        if (cached) {
          const data = JSON.parse(cached);
          const newStep = data.quickStartStep ?? null;
          const newStep4Progress = data.step4Progress ?? DEFAULT_STEP4_PROGRESS;

          setLocalStep(newStep);
          setLocalStep4Progress(newStep4Progress);

          // If step becomes null, wizard was completed
          if (newStep === null && localStep !== null) {
            setWasCompleted(true);
          } else if (newStep !== null) {
            // If a new step is set, reset completed state (wizard restarted)
            setWasCompleted(false);
          }
        }
      } catch {
        // Ignore parse errors
      }
    };

    // Handle custom event for same-tab instant updates
    const handleStateChange = (e: CustomEvent<{ quickStartStep?: number | null; step4Progress?: Step4Progress }>) => {
      const newStep = e.detail?.quickStartStep ?? null;
      const newStep4Progress = e.detail?.step4Progress ?? DEFAULT_STEP4_PROGRESS;

      setLocalStep(newStep);
      setLocalStep4Progress(newStep4Progress);

      // If step becomes null, wizard was completed
      if (newStep === null) {
        setWasCompleted(true);
      } else {
        // If a new step is set, reset dismissed and completed states
        setDismissed(false);
        setWasCompleted(false);
      }
    };

    // Listen for storage events (from other tabs/windows)
    window.addEventListener('storage', checkLocalStorage);

    // Listen for custom event (from same tab, other hook instances)
    window.addEventListener('onboarding-state-change', handleStateChange as EventListener);

    return () => {
      window.removeEventListener('storage', checkLocalStorage);
      window.removeEventListener('onboarding-state-change', handleStateChange as EventListener);
    };
  }, [localStep]);

  // Use localStorage values directly - they're read synchronously and always up-to-date
  const effectiveStep = localStep;
  const effectiveStep4Progress = localStep4Progress;

  // Don't show if dismissed, completed, or no step in progress
  // We rely solely on localStorage state (localStep) which is synchronously updated
  const showButton = !dismissed && !wasCompleted && localStep !== null;

  if (!showButton || !effectiveStep) {
    return null;
  }

  // Compute what action to show for Step 4
  const getStep4Action = (): Step4NextAction => {
    if (effectiveStep4Progress.visitedIntegrations && effectiveStep4Progress.visitedAgentConfig) {
      return 'complete';
    }
    if (effectiveStep4Progress.visitedIntegrations) {
      return 'agent-config';
    }
    return 'integrations';
  };

  const step4Action = effectiveStep === 4 ? getStep4Action() : undefined;

  // Get display name - for Step 4, show what's next based on progress
  const getDisplayName = (): string => {
    if (effectiveStep === 4) {
      switch (step4Action) {
        case 'agent-config':
          return 'Agent Config';
        case 'integrations':
          return 'Integrations';
        case 'complete':
          return 'Try It Now';
        default:
          return 'Configure Agents';
      }
    }
    // Step 5: Prompt to run an investigation
    if (effectiveStep === 5) {
      return 'Run Investigation';
    }
    // Step 6: Complete the setup
    if (effectiveStep === 6) {
      return 'Finish Setup';
    }
    return STEP_NAMES[effectiveStep] || `Step ${effectiveStep}`;
  };

  const stepName = getDisplayName();

  const handleContinue = () => {
    onContinue(effectiveStep, step4Action);
  };

  const handleDismiss = () => {
    setDismissed(true);
    clearQuickStartStep();
  };

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-top-2 duration-300">
      <div className="flex items-center gap-3 px-4 py-3 bg-orange-600 text-white rounded-xl shadow-lg">
        <span className="text-sm font-medium">
          Continue setup: {stepName}
        </span>
        <button
          onClick={handleContinue}
          className="flex items-center gap-1 px-3 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg text-sm font-medium transition-colors"
        >
          Continue
          <ArrowRight className="w-4 h-4" />
        </button>
        <button
          onClick={handleDismiss}
          className="p-1 hover:bg-white/20 rounded transition-colors"
          aria-label="Dismiss"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
