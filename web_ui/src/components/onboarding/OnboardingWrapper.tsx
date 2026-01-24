'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ContinueOnboardingButton } from './ContinueOnboardingButton';
import { QuickStartWizard } from './QuickStartWizard';
import { useOnboarding, type Step4NextAction } from '@/lib/useOnboarding';

interface OnboardingWrapperProps {
  children: React.ReactNode;
}

/**
 * Wrapper component that provides global onboarding UI (floating button + wizard).
 * Should be placed high in the component tree to appear on all pages.
 */
export function OnboardingWrapper({ children }: OnboardingWrapperProps) {
  const router = useRouter();
  const [showWizard, setShowWizard] = useState(false);
  const [wizardInitialStep, setWizardInitialStep] = useState(1);
  const { markStep4IntegrationsVisited, markStep4AgentConfigVisited, setQuickStartStep } = useOnboarding();

  const handleContinueOnboarding = useCallback((step: number, step4Action?: Step4NextAction) => {
    // For Step 4, navigate directly to the appropriate page based on what's missing
    // AND mark that page as visited
    if (step === 4 && step4Action) {
      switch (step4Action) {
        case 'integrations':
          markStep4IntegrationsVisited();
          router.push('/team/tools');
          return;
        case 'agent-config':
          markStep4AgentConfigVisited();
          router.push('/team/agents');
          return;
        case 'complete':
          // Both done - advance to step 5 (Try It Now)
          setQuickStartStep(5);
          router.push('/team/agent-runs');
          return;
      }
    }

    // For Step 5, navigate to agent-runs page (if not already there)
    if (step === 5) {
      router.push('/team/agent-runs');
      return;
    }

    // For Step 6, open the wizard at the congratulations screen
    if (step === 6) {
      setWizardInitialStep(6);
      setShowWizard(true);
      return;
    }

    // For other steps, open the wizard
    setWizardInitialStep(step);
    setShowWizard(true);
  }, [router, markStep4IntegrationsVisited, markStep4AgentConfigVisited, setQuickStartStep]);

  const handleCloseWizard = useCallback(() => {
    setShowWizard(false);
  }, []);

  const handleRunAgent = useCallback(() => {
    // This is called when user wants to run an agent from the wizard
    // For now, just close the wizard - the user will be on the agent-runs page
    setShowWizard(false);
  }, []);

  const handleSkip = useCallback(() => {
    setShowWizard(false);
  }, []);

  return (
    <>
      {children}

      {/* Floating continue button - appears when user navigates away mid-wizard */}
      <ContinueOnboardingButton onContinue={handleContinueOnboarding} />

      {/* Quick Start Wizard modal */}
      {showWizard && (
        <QuickStartWizard
          onClose={handleCloseWizard}
          onRunAgent={handleRunAgent}
          onSkip={handleSkip}
          initialStep={wizardInitialStep}
        />
      )}
    </>
  );
}
