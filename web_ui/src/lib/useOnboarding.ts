'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from './apiClient';

export interface Step4Progress {
  visitedIntegrations: boolean;
  visitedAgentConfig: boolean;
}

export interface OnboardingState {
  welcomeModalSeen: boolean;
  firstAgentRunCompleted: boolean;
  completedAt?: string;
  // Quick Start wizard progress (null = not in progress, 1-6 = current step to resume)
  quickStartStep?: number | null;
  // Step 4 sub-task progress (user must visit both before advancing to step 5)
  step4Progress?: Step4Progress;
}

// What action to show in the floating button for Step 4
export type Step4NextAction = 'integrations' | 'agent-config' | 'complete';

const DEFAULT_STEP4_PROGRESS: Step4Progress = {
  visitedIntegrations: false,
  visitedAgentConfig: false,
};

const DEFAULT_STATE: OnboardingState = {
  welcomeModalSeen: false,
  firstAgentRunCompleted: false,
  quickStartStep: null,
  step4Progress: DEFAULT_STEP4_PROGRESS,
};

const LOCALSTORAGE_KEY = 'incidentfox_onboarding';

interface UseOnboardingOptions {
  /** When true, uses localStorage only (no server calls). Used for visitors. */
  isVisitor?: boolean;
}

export function useOnboarding(options: UseOnboardingOptions = {}) {
  const { isVisitor = false } = options;
  const isVisitorRef = useRef(isVisitor);
  isVisitorRef.current = isVisitor;

  const [state, setState] = useState<OnboardingState>(DEFAULT_STATE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load onboarding state from localStorage
  const loadFromLocalStorage = useCallback(() => {
    const cached = localStorage.getItem(LOCALSTORAGE_KEY);
    if (cached) {
      try {
        setState(JSON.parse(cached));
      } catch {
        setState(DEFAULT_STATE);
      }
    } else {
      setState(DEFAULT_STATE);
    }
  }, []);

  // Load onboarding state
  const loadState = useCallback(async () => {
    // Visitors use localStorage only - no server calls
    if (isVisitorRef.current) {
      setLoading(true);
      loadFromLocalStorage();
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const res = await apiFetch('/api/team/preferences');

      if (res.ok) {
        const data = await res.json();
        setState({
          welcomeModalSeen: data.onboarding?.welcomeModalSeen ?? false,
          firstAgentRunCompleted: data.onboarding?.firstAgentRunCompleted ?? false,
          completedAt: data.onboarding?.completedAt,
          quickStartStep: data.onboarding?.quickStartStep ?? null,
          step4Progress: data.onboarding?.step4Progress ?? DEFAULT_STEP4_PROGRESS,
        });
      } else if (res.status === 401) {
        // Not authenticated - use default state
        setState(DEFAULT_STATE);
      } else {
        // On error, use localStorage fallback
        loadFromLocalStorage();
      }
    } catch (e) {
      // Use localStorage fallback
      loadFromLocalStorage();
    } finally {
      setLoading(false);
    }
  }, [loadFromLocalStorage]);

  // Save onboarding state
  const updateState = useCallback(async (updates: Partial<OnboardingState>) => {
    const newState = { ...state, ...updates };
    setState(newState);

    // Save to localStorage
    localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(newState));

    // Dispatch custom event for same-tab listeners
    window.dispatchEvent(new CustomEvent('onboarding-state-change', { detail: newState }));

    // Visitors don't sync to server - localStorage only
    if (isVisitorRef.current) {
      return;
    }

    try {
      await apiFetch('/api/team/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          onboarding: newState,
        }),
      });
    } catch (e) {
      // Silently fail - localStorage is the fallback
    }
  }, [state]);

  // Mark welcome modal as seen
  const markWelcomeSeen = useCallback(() => {
    updateState({ welcomeModalSeen: true });
  }, [updateState]);

  // Mark first agent run as completed
  const markFirstAgentRunCompleted = useCallback(() => {
    updateState({
      firstAgentRunCompleted: true,
      completedAt: new Date().toISOString(),
    });
  }, [updateState]);

  // Reset onboarding (for testing)
  const resetOnboarding = useCallback(() => {
    localStorage.removeItem(LOCALSTORAGE_KEY);
    setState(DEFAULT_STATE);

    // Visitors don't sync to server
    if (isVisitorRef.current) {
      return;
    }

    apiFetch('/api/team/preferences', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        onboarding: DEFAULT_STATE,
      }),
    }).catch(() => {});
  }, []);

  // Save quick start step (call when user navigates away mid-wizard)
  const setQuickStartStep = useCallback((step: number | null) => {
    updateState({ quickStartStep: step });
  }, [updateState]);

  // Clear quick start step (call when wizard completes or user dismisses)
  const clearQuickStartStep = useCallback(() => {
    updateState({ quickStartStep: null, step4Progress: DEFAULT_STEP4_PROGRESS });
  }, [updateState]);

  // Mark Step 4 Integrations as visited
  const markStep4IntegrationsVisited = useCallback(() => {
    const currentProgress = state.step4Progress ?? DEFAULT_STEP4_PROGRESS;
    const newProgress = { ...currentProgress, visitedIntegrations: true };

    // If both are now visited, advance to step 5
    if (newProgress.visitedIntegrations && newProgress.visitedAgentConfig) {
      updateState({ quickStartStep: 5, step4Progress: newProgress });
    } else {
      // Stay on step 4, but save progress
      updateState({ quickStartStep: 4, step4Progress: newProgress });
    }
  }, [state.step4Progress, updateState]);

  // Mark Step 4 Agent Config as visited
  const markStep4AgentConfigVisited = useCallback(() => {
    const currentProgress = state.step4Progress ?? DEFAULT_STEP4_PROGRESS;
    const newProgress = { ...currentProgress, visitedAgentConfig: true };

    // If both are now visited, advance to step 5
    if (newProgress.visitedIntegrations && newProgress.visitedAgentConfig) {
      updateState({ quickStartStep: 5, step4Progress: newProgress });
    } else {
      // Stay on step 4, but save progress
      updateState({ quickStartStep: 4, step4Progress: newProgress });
    }
  }, [state.step4Progress, updateState]);

  // Get what action to show next for Step 4
  const getStep4NextAction = useCallback((): Step4NextAction => {
    const progress = state.step4Progress ?? DEFAULT_STEP4_PROGRESS;
    if (progress.visitedIntegrations && progress.visitedAgentConfig) {
      return 'complete';
    }
    if (progress.visitedIntegrations) {
      return 'agent-config';
    }
    return 'integrations';
  }, [state.step4Progress]);

  // Check if onboarding is complete
  const isComplete = state.welcomeModalSeen && state.firstAgentRunCompleted;

  // Check if user has a paused quick start wizard
  const hasQuickStartInProgress = state.quickStartStep !== null && state.quickStartStep !== undefined;

  // Check if should show welcome modal
  const shouldShowWelcome = !loading && !state.welcomeModalSeen;

  useEffect(() => {
    loadState();
  }, [loadState]);

  return {
    state,
    loading,
    error,
    isComplete,
    shouldShowWelcome,
    hasQuickStartInProgress,
    markWelcomeSeen,
    markFirstAgentRunCompleted,
    setQuickStartStep,
    clearQuickStartStep,
    markStep4IntegrationsVisited,
    markStep4AgentConfigVisited,
    getStep4NextAction,
    resetOnboarding,
    reload: loadState,
  };
}
