'use client';

import { useEffect, useMemo, useState } from 'react';
import { useIdentity } from '@/lib/useIdentity';
import { applyTheme, getTheme, setTheme, type ThemeMode } from '@/lib/theme';
import { X, KeyRound, Shield, Chrome, Building2, Loader2, Lock } from 'lucide-react';

interface OrgSSOConfig {
  enabled: boolean;
  provider_type: string;
  provider_name: string;
  issuer?: string;
  client_id?: string;
  tenant_id?: string;
  scopes?: string;
}

export function SignInGate({ children }: { children: React.ReactNode }) {
  const { identity, loading, error, refresh } = useIdentity();
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [ssoConfig, setSsoConfig] = useState<OrgSSOConfig | null>(null);
  const [loadingSSO, setLoadingSSO] = useState(true);

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

  if (canShowApp) return <>{children}</>;

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
                {hasSSO ? 'Use SSO or paste a token to continue.' : 'Paste an admin token or team token to continue.'}
              </div>
            </div>
          </div>

          <button
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
            onClick={() => {
              setToken('');
              setSubmitError(null);
            }}
            title="Clear"
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="p-6 space-y-4">
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

            <button
              onClick={login}
              disabled={submitting || !token.trim()}
              className="px-4 py-2 text-sm font-semibold bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-70"
            >
              {submitting ? 'Signing in…' : 'Continue'}
            </button>
          </div>
        </div>

        <div className="p-4 bg-gray-50 dark:bg-gray-950/30 border-t border-gray-200 dark:border-gray-800 text-xs text-gray-500">
          Enterprise default: tokens are stored in a secure session cookie (not localStorage).
        </div>
      </div>
    </div>
  );
}
