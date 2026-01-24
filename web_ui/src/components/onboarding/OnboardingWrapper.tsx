'use client';

import { useState, useCallback } from 'react';
import { ContinueOnboardingButton } from './ContinueOnboardingButton';
import { QuickStartWizard } from './QuickStartWizard';
import type { Step4NextAction } from '@/lib/useOnboarding';

interface OnboardingWrapperProps {
  children: React.ReactNode;
}

/**
 * Wrapper component that provides global onboarding UI (floating button + wizard).
 * Should be placed high in the component tree to appear on all pages.
 */
export function OnboardingWrapper({ children }: OnboardingWrapperProps) {
  const [showWizard, setShowWizard] = useState(false);
  const [wizardInitialStep, setWizardInitialStep] = useState(1);

  const handleContinueOnboarding = useCallback((step: number, _step4Action?: Step4NextAction) => {
    // For all steps, open the wizard modal first
    // Steps 4 and 5 have navigation buttons inside the modal content
    // that users can click to go to the actual pages
    setWizardInitialStep(step);
    setShowWizard(true);
  }, []);

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
