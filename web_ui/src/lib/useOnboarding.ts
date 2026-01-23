'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from './apiClient';

export interface OnboardingState {
  welcomeModalSeen: boolean;
  firstAgentRunCompleted: boolean;
  completedAt?: string;
}

const DEFAULT_STATE: OnboardingState = {
  welcomeModalSeen: false,
  firstAgentRunCompleted: false,
};

export function useOnboarding() {
  const [state, setState] = useState<OnboardingState>(DEFAULT_STATE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load onboarding state
  const loadState = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiFetch('/api/team/preferences');

      if (res.ok) {
        const data = await res.json();
        setState({
          welcomeModalSeen: data.onboarding?.welcomeModalSeen ?? false,
          firstAgentRunCompleted: data.onboarding?.firstAgentRunCompleted ?? false,
          completedAt: data.onboarding?.completedAt,
        });
      } else if (res.status === 401) {
        // Not authenticated - use default state
        setState(DEFAULT_STATE);
      } else {
        // On error, use localStorage fallback
        const cached = localStorage.getItem('incidentfox_onboarding');
        if (cached) {
          setState(JSON.parse(cached));
        }
      }
    } catch (e) {
      // Use localStorage fallback
      const cached = localStorage.getItem('incidentfox_onboarding');
      if (cached) {
        setState(JSON.parse(cached));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Save onboarding state
  const updateState = useCallback(async (updates: Partial<OnboardingState>) => {
    const newState = { ...state, ...updates };
    setState(newState);

    // Save to localStorage as fallback
    localStorage.setItem('incidentfox_onboarding', JSON.stringify(newState));

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
    localStorage.removeItem('incidentfox_onboarding');
    setState(DEFAULT_STATE);
    apiFetch('/api/team/preferences', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        onboarding: DEFAULT_STATE,
      }),
    }).catch(() => {});
  }, []);

  // Check if onboarding is complete
  const isComplete = state.welcomeModalSeen && state.firstAgentRunCompleted;

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
    markWelcomeSeen,
    markFirstAgentRunCompleted,
    resetOnboarding,
    reload: loadState,
  };
}
