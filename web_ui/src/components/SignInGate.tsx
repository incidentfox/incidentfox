'use client';

import { useEffect, useMemo, useState } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import { applyTheme, getTheme, setTheme, type ThemeMode } from '@/lib/theme';
import { X, KeyRound, Shield, Chrome, Building2, Loader2, Lock, Mail, Users, Clock } from 'lucide-react';
import { OnboardingWrapper } from './onboarding/OnboardingWrapper';

interface OrgSSOConfig {
  enabled: boolean;
  provider_type: string;
  provider_name: string;
  issuer?: string;
  client_id?: string;
  tenant_id?: string;
  scopes?: string;
}

type LoginMode = 'team' | 'visitor';

interface VisitorSession {
  session_id: string;
  status: 'active' | 'queued';
  queue_position?: number;
  estimated_wait_seconds?: number;
  token?: string;
}

export function SignInGate({ children }: { children: React.ReactNode }) {
  const { identity, loading, error, refresh } = useIdentity();
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [ssoConfig, setSsoConfig] = useState<OrgSSOConfig | null>(null);
  const [loadingSSO, setLoadingSSO] = useState(true);

  // Visitor login state
  const [loginMode, setLoginMode] = useState<LoginMode>('team');
  const [visitorEmail, setVisitorEmail] = useState('');
  const [visitorSession, setVisitorSession] = useState<VisitorSession | null>(null);

  const [theme, setThemeState] = useState<ThemeMode>('dark');

  useEffect(() => {
    const t = getTheme();
    setThemeState(t);
    applyTheme(t);
  }, []);

  // Load org SSO config
  useEffect(() => {
    fetch('/api/sso/config?org_id=org1')
      .then((res) => res.json())
      .then((data) => {
        if (data.enabled) {
          setSsoConfig(data);
        }
        setLoadingSSO(false);
      })
      .catch(() => {
        setLoadingSSO(false);
      });
  }, []);

  const canShowApp = !loading && !!identity;

  const helpText = useMemo(() => {
    if (submitError) return submitError;
    if (error) return error;
    return null;
  }, [error, submitError]);

  const login = async () => {
    setSubmitting(true);
    setSubmitError(null);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch('/api/session/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ token: token.trim() }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
      await refresh();
    } catch (e: any) {
      clearTimeout(timeoutId);
      if (e?.name === 'AbortError') {
        setSubmitError('Login request timed out. Please check your network connection and try again.');
      } else {
        setSubmitError(e?.message || String(e));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Visitor login handler
  const loginAsVisitor = async () => {
    setSubmitting(true);
    setSubmitError(null);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch('/api/visitor/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email: visitorEmail.trim() }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || `${res.status} ${res.statusText}`);
      }

      if (data.status === 'active') {
        // Got immediate access - refresh identity
        await refresh();
      } else if (data.status === 'queued') {
        // Added to queue - show queue UI
        setVisitorSession(data);
      }
    } catch (e: any) {
      clearTimeout(timeoutId);
      if (e?.name === 'AbortError') {
        setSubmitError('Login request timed out. Please check your network connection and try again.');
      } else {
        setSubmitError(e?.message || String(e));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Poll for queue status when visitor is queued
  useEffect(() => {
    if (!visitorSession || visitorSession.status !== 'queued') return;

    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch('/api/visitor/heartbeat', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
        });
        const data = await res.json();

        if (data.status === 'active') {
          // Promoted to active - refresh identity
          setVisitorSession(null);
          await refresh();
        } else if (data.status === 'queued') {
          // Update queue position
          setVisitorSession((prev) =>
            prev ? { ...prev, queue_position: data.queue_position, estimated_wait_seconds: data.estimated_wait_seconds } : null
          );
        } else if (data.status === 'expired') {
          // Session expired
          setVisitorSession(null);
          setSubmitError('Your queue position expired. Please try again.');
        }
      } catch (e) {
        console.error('Failed to poll queue status:', e);
      }
    }, 5000); // Poll every 5 seconds

    return () => clearInterval(pollInterval);
  }, [visitorSession, refresh]);

  const handleSSOLogin = () => {
    if (!ssoConfig) return;

    // Build the OIDC authorization URL
    let authUrl: string;
    const redirectUri = `${window.location.origin}/api/auth/callback`;
    const state = btoa(JSON.stringify({ org_id: 'org1', returnTo: '/' }));
    const scopes = ssoConfig.scopes || 'openid email profile';

    if (ssoConfig.provider_type === 'google') {
      authUrl = `https://accounts.google.com/o/oauth2/v2/auth?` +
        `client_id=${ssoConfig.client_id}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scopes)}` +
        `&state=${state}` +
        `&access_type=offline` +
        `&prompt=select_account`;
    } else if (ssoConfig.provider_type === 'azure') {
      const tenant = ssoConfig.tenant_id || 'common';
      authUrl = `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/authorize?` +
        `client_id=${ssoConfig.client_id}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scopes)}` +
        `&state=${state}` +
        `&response_mode=query`;
    } else {
      // Generic OIDC
      const issuer = ssoConfig.issuer?.replace(/\/$/, '');
      authUrl = `${issuer}/authorize?` +
        `client_id=${ssoConfig.client_id}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scopes)}` +
        `&state=${state}`;
    }

    window.location.href = authUrl;
  };

  const getProviderIcon = (providerType: string) => {
    switch (providerType) {
      case 'google':
        return <Chrome className="w-4 h-4" />;
      case 'azure':
        return <Building2 className="w-4 h-4" />;
      case 'okta':
        return <Lock className="w-4 h-4" />;
      default:
        return <Shield className="w-4 h-4" />;
    }
  };

  const hasSSO = ssoConfig?.enabled;

  // Email validation
  const isValidEmail = (email: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  };

  // Format wait time
  const formatWaitTime = (seconds: number) => {
    if (seconds < 60) return 'less than a minute';
    const minutes = Math.ceil(seconds / 60);
    return `about ${minutes} minute${minutes > 1 ? 's' : ''}`;
  };

  if (canShowApp) return <OnboardingWrapper>{children}</OnboardingWrapper>;

  // Show queue overlay if waiting
  if (visitorSession && visitorSession.status === 'queued') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-black p-6">
        <div className="w-full max-w-md bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl shadow-xl overflow-hidden">
          <div className="p-6 border-b border-gray-200 dark:border-gray-800">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-orange-600 text-white flex items-center justify-center">
                <Users className="w-5 h-5" />
              </div>
              <div>
                <div className="text-base font-semibold text-gray-900 dark:text-white">You&apos;re in the queue</div>
                <div className="text-xs text-gray-500">Please wait for your turn</div>
              </div>
            </div>
          </div>

          <div className="p-6 space-y-6">
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600 mb-2">
                #{visitorSession.queue_position || 1}
              </div>
              <div className="text-sm text-gray-500">Your position in queue</div>
            </div>

            {visitorSession.estimated_wait_seconds && (
              <div className="flex items-center justify-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                <Clock className="w-4 h-4" />
                <span>Estimated wait: {formatWaitTime(visitorSession.estimated_wait_seconds)}</span>
              </div>
            )}

            <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 text-sm text-gray-600 dark:text-gray-400">
              <p>
                The playground allows one user at a time to ensure a great experience.
                You&apos;ll be automatically connected when it&apos;s your turn.
              </p>
            </div>

            <div className="flex items-center justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-orange-600 mr-2" />
              <span className="text-sm text-gray-500">Waiting for your turn...</span>
            </div>

            <button
              onClick={() => {
                setVisitorSession(null);
                fetch('/api/visitor/end-session', { method: 'POST' });
              }}
              className="w-full px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Leave queue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-black p-6">
      <div className="w-full max-w-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl shadow-xl overflow-hidden">
        <div className="p-6 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-orange-600 text-white flex items-center justify-center">
              <KeyRound className="w-5 h-5" />
            </div>
            <div>
              <div className="text-base font-semibold text-gray-900 dark:text-white">Sign in to IncidentFox</div>
              <div className="text-xs text-gray-500">
                {loginMode === 'team'
                  ? hasSSO
                    ? 'Use SSO or paste a token to continue.'
                    : 'Paste an admin token or team token to continue.'
                  : 'Enter your email to try the playground.'}
              </div>
            </div>
          </div>

          <button
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
            onClick={() => {
              setToken('');
              setVisitorEmail('');
              setSubmitError(null);
            }}
            title="Clear"
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Login Mode Tabs */}
        <div className="flex border-b border-gray-200 dark:border-gray-800">
          <button
            onClick={() => {
              setLoginMode('team');
              setSubmitError(null);
            }}
            className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
              loginMode === 'team'
                ? 'text-orange-600 border-b-2 border-orange-600 bg-orange-50/50 dark:bg-orange-900/10'
                : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <KeyRound className="w-4 h-4" />
              Team Login
            </div>
          </button>
          <button
            onClick={() => {
              setLoginMode('visitor');
              setSubmitError(null);
            }}
            className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
              loginMode === 'visitor'
                ? 'text-orange-600 border-b-2 border-orange-600 bg-orange-50/50 dark:bg-orange-900/10'
                : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <Mail className="w-4 h-4" />
              Try for Free
            </div>
          </button>
        </div>

        <div className="p-6 space-y-4">
          {loginMode === 'team' ? (
            <>
              {/* SSO Button */}
              {loadingSSO ? (
                <div className="flex items-center justify-center py-2">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              ) : hasSSO && ssoConfig ? (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">Single Sign-On</div>
                  <button
                    onClick={handleSSOLogin}
                    className="w-full px-4 py-2.5 text-sm font-semibold bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 flex items-center justify-center gap-2 transition-colors"
                  >
                    {getProviderIcon(ssoConfig.provider_type)}
                    Continue with {ssoConfig.provider_name}
                  </button>
                  <div className="flex items-center gap-3 py-2">
                    <div className="flex-1 border-t border-gray-200 dark:border-gray-700" />
                    <span className="text-xs text-gray-400">or</span>
                    <div className="flex-1 border-t border-gray-200 dark:border-gray-700" />
                  </div>
                </div>
              ) : null}

              {/* Token Login */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Token</label>
                <textarea
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  rows={3}
                  placeholder="tokid.toksecret or JWT"
                  className="w-full p-3 font-mono text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>
            </>
          ) : (
            <>
              {/* Visitor Login */}
              <div className="bg-orange-50 dark:bg-orange-900/20 border border-orange-100 dark:border-orange-900/40 rounded-lg p-4 text-sm">
                <p className="text-orange-800 dark:text-orange-200 font-medium mb-1">
                  Try IncidentFox for free
                </p>
                <p className="text-orange-700 dark:text-orange-300 text-xs">
                  Enter your email to access our public playground. You&apos;ll get to explore the AI-powered incident investigation platform.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Email</label>
                <input
                  type="email"
                  value={visitorEmail}
                  onChange={(e) => setVisitorEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="w-full p-3 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 focus:outline-none focus:ring-2 focus:ring-orange-500"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && isValidEmail(visitorEmail) && !submitting) {
                      loginAsVisitor();
                    }
                  }}
                />
              </div>

              <div className="text-xs text-gray-500">
                By continuing, you agree to receive occasional updates about IncidentFox.
              </div>
            </>
          )}

          {helpText ? (
            <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/40 rounded-lg p-3">
              {helpText}
            </div>
          ) : null}

          <div className="flex items-center justify-between gap-3 pt-2">
            <button
              onClick={() => {
                const next: ThemeMode = theme === 'dark' ? 'light' : 'dark';
                setThemeState(next);
                setTheme(next);
              }}
              className="px-3 py-2 text-sm font-medium bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
            >
              Theme: {theme === 'dark' ? 'Dark' : 'Light'}
            </button>

            {loginMode === 'team' ? (
              <button
                onClick={login}
                disabled={submitting || !token.trim()}
                className="px-4 py-2 text-sm font-semibold bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-70"
              >
                {submitting ? 'Signing in...' : 'Continue'}
              </button>
            ) : (
              <button
                onClick={loginAsVisitor}
                disabled={submitting || !isValidEmail(visitorEmail)}
                className="px-4 py-2 text-sm font-semibold bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-70"
              >
                {submitting ? 'Signing in...' : 'Try Playground'}
              </button>
            )}
          </div>
        </div>

        <div className="p-4 bg-gray-50 dark:bg-gray-950/30 border-t border-gray-200 dark:border-gray-800 text-xs text-gray-500">
          {loginMode === 'team'
            ? 'Enterprise default: tokens are stored in a secure session cookie (not localStorage).'
            : 'Visitor sessions are limited. One user at a time can use the playground.'}
        </div>
      </div>
    </div>
  );
}
