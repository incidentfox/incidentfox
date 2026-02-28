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

/** Read onboarding state from localStorage, returning DEFAULT_STATE on missing/corrupt data. */
function readLocalStorage(): OnboardingState {
  try {
    const cached = localStorage.getItem(LOCALSTORAGE_KEY);
    if (cached) {
      return JSON.parse(cached);
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_STATE;
}

/** Merge two onboarding states, keeping the "more progressed" value (true wins over false). */
function mergeStates(a: OnboardingState, b: OnboardingState): OnboardingState {
  return {
    welcomeModalSeen: a.welcomeModalSeen || b.welcomeModalSeen,
    firstAgentRunCompleted: a.firstAgentRunCompleted || b.firstAgentRunCompleted,
    completedAt: a.completedAt || b.completedAt,
    quickStartStep: a.quickStartStep ?? b.quickStartStep,
    step4Progress: {
      visitedIntegrations:
        (a.step4Progress?.visitedIntegrations || b.step4Progress?.visitedIntegrations) ?? false,
      visitedAgentConfig:
        (a.step4Progress?.visitedAgentConfig || b.step4Progress?.visitedAgentConfig) ?? false,
    },
  };
}

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

  // Ref tracks the latest committed state so updateState can read it
  // outside the React render cycle (for localStorage + server writes).
  const stateRef = useRef<OnboardingState>(DEFAULT_STATE);

  // Keep stateRef in sync with React state
  const setStateAndRef = useCallback((next: OnboardingState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  // Load onboarding state from localStorage
  const loadFromLocalStorage = useCallback(() => {
    const localState = readLocalStorage();
    setStateAndRef(localState);
  }, [setStateAndRef]);

  // Load onboarding state — merges server + localStorage so completed
  // steps are never lost even if one source is stale.
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

      // Always read localStorage as a baseline
      const localState = readLocalStorage();

      if (res.ok) {
        const data = await res.json();
        const serverState: OnboardingState = {
          welcomeModalSeen: data.onboarding?.welcomeModalSeen ?? false,
          firstAgentRunCompleted: data.onboarding?.firstAgentRunCompleted ?? false,
          completedAt: data.onboarding?.completedAt,
          quickStartStep: data.onboarding?.quickStartStep ?? null,
          step4Progress: data.onboarding?.step4Progress ?? DEFAULT_STEP4_PROGRESS,
        };

        // Merge: true (completed) wins over false — if either source
        // says a step is done we trust it.
        const merged = mergeStates(serverState, localState);
        setStateAndRef(merged);
        localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(merged));
      } else if (res.status === 401) {
        // Not authenticated - use default state
        setStateAndRef(DEFAULT_STATE);
      } else {
        // On error, use localStorage fallback
        setStateAndRef(localState);
      }
    } catch (e) {
      // Use localStorage fallback
      loadFromLocalStorage();
    } finally {
      setLoading(false);
    }
  }, [loadFromLocalStorage, setStateAndRef]);

  // Save onboarding state.
  // Uses a functional setState so rapid successive calls (e.g. markWelcomeSeen +
  // markFirstAgentRunCompleted in the same tick) merge correctly instead of
  // the second call overwriting the first with stale closure state.
  const updateState = useCallback((updates: Partial<OnboardingState>) => {
    setState(prev => {
      const newState = { ...prev, ...updates };
      stateRef.current = newState;

      // Save to localStorage synchronously so other components/tabs pick it up
      localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(newState));

      // Dispatch custom event for same-tab listeners
      window.dispatchEvent(new CustomEvent('onboarding-state-change', { detail: newState }));

      // Async server sync — fire-and-forget but log failures
      if (!isVisitorRef.current) {
        apiFetch('/api/team/preferences', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ onboarding: newState }),
        }).catch(e => {
          console.warn('[onboarding] Failed to save to server:', e);
        });
      }

      return newState;
    });
  }, []);

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
    setStateAndRef(DEFAULT_STATE);

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
    }).catch(e => {
      console.warn('[onboarding] Failed to reset on server:', e);
    });
  }, [setStateAndRef]);

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
    setState(prev => {
      const currentProgress = prev.step4Progress ?? DEFAULT_STEP4_PROGRESS;
      const newProgress = { ...currentProgress, visitedIntegrations: true };

      // If both are now visited, advance to step 5
      if (newProgress.visitedIntegrations && newProgress.visitedAgentConfig) {
        updateState({ quickStartStep: 5, step4Progress: newProgress });
      } else {
        // Stay on step 4, but save progress
        updateState({ quickStartStep: 4, step4Progress: newProgress });
      }
      return prev; // updateState handles the actual state change
    });
  }, [updateState]);

  // Mark Step 4 Agent Config as visited
  const markStep4AgentConfigVisited = useCallback(() => {
    setState(prev => {
      const currentProgress = prev.step4Progress ?? DEFAULT_STEP4_PROGRESS;
      const newProgress = { ...currentProgress, visitedAgentConfig: true };

      // If both are now visited, advance to step 5
      if (newProgress.visitedIntegrations && newProgress.visitedAgentConfig) {
        updateState({ quickStartStep: 5, step4Progress: newProgress });
      } else {
        // Stay on step 4, but save progress
        updateState({ quickStartStep: 4, step4Progress: newProgress });
      }
      return prev; // updateState handles the actual state change
    });
  }, [updateState]);

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
