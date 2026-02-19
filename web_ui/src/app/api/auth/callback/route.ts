import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import crypto from 'crypto';

const CONFIG_SERVICE_URL = process.env.CONFIG_SERVICE_URL || 'http://localhost:8080';

/**
 * Validate returnTo is a safe relative path (prevent open redirect).
 */
function safeReturnTo(returnTo: string | undefined): string {
  if (!returnTo) return '/';
  // Only allow relative paths starting with /
  if (!returnTo.startsWith('/') || returnTo.startsWith('//')) return '/';
  return returnTo;
}

/**
 * Timing-safe comparison of two strings.
 */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
}

/**
 * OAuth callback handler.
 * Exchanges the auth code for tokens, validates the user, and creates a session.
 */
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get('code');
  const state = searchParams.get('state');
  const error = searchParams.get('error');

  if (error) {
    return NextResponse.redirect(new URL(`/?error=${encodeURIComponent(error)}`, request.url));
  }

  if (!code) {
    return NextResponse.redirect(new URL('/?error=no_code', request.url));
  }

  // Validate OIDC state against cookie to prevent CSRF
  const cookieStore = await cookies();
  const savedState = cookieStore.get('ifx_oidc_state')?.value;

  if (savedState) {
    // OIDC flow: state must match the cookie set during /api/auth/login
    if (!state || !timingSafeEqual(state, savedState)) {
      return NextResponse.redirect(new URL('/?error=invalid_state', request.url));
    }
  } else if (!state) {
    // No state cookie and no state param — reject
    return NextResponse.redirect(new URL('/?error=missing_state', request.url));
  }

  // Parse state for SSO flow metadata (org_id, returnTo).
  // For OIDC flow (random state), this parse will fail and we use defaults.
  let stateData = { org_id: 'org1', returnTo: '/' };
  if (state && !savedState) {
    // Only parse state as JSON for the SSO flow (no OIDC cookie)
    try {
      stateData = JSON.parse(atob(state));
    } catch {
      // ignore parse failure — use defaults
    }
  }

  try {
    // Get org SSO config from config service
    // Sanitize org_id to prevent path traversal
    const orgId = (stateData.org_id || '').replace(/[^a-zA-Z0-9_-]/g, '');
    if (!orgId) {
      return NextResponse.redirect(new URL('/?error=invalid_org', request.url));
    }

    const ssoConfigRes = await fetch(
      `${CONFIG_SERVICE_URL}/api/v1/admin/orgs/${orgId}/sso-config/public`
    );

    if (!ssoConfigRes.ok) {
      return NextResponse.redirect(new URL('/?error=sso_not_configured', request.url));
    }

    const ssoConfig = await ssoConfigRes.json();

    if (!ssoConfig.enabled) {
      return NextResponse.redirect(new URL('/?error=sso_disabled', request.url));
    }

    const redirectUri = `${request.nextUrl.origin}/api/auth/callback`;

    // Include PKCE verifier if available (set by /api/auth/login)
    const codeVerifier = cookieStore.get('ifx_oidc_verifier')?.value;

    // Exchange code for token via config service
    const exchangeRes = await fetch(
      `${CONFIG_SERVICE_URL}/api/v1/auth/sso/exchange`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org_id: orgId,
          code,
          redirect_uri: redirectUri,
          ...(codeVerifier ? { code_verifier: codeVerifier } : {}),
        }),
      }
    );

    if (!exchangeRes.ok) {
      const err = await exchangeRes.json().catch(() => ({}));
      console.error('Token exchange failed:', err);
      return NextResponse.redirect(new URL(`/?error=exchange_failed&detail=${encodeURIComponent(err.detail || '')}`, request.url));
    }

    const exchangeData = await exchangeRes.json();

    // Set session cookie with the session token
    const res = NextResponse.redirect(new URL(safeReturnTo(stateData.returnTo), request.url));
    res.cookies.set('incidentfox_session_token', exchangeData.session_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    // Clean up temporary OIDC cookies
    res.cookies.delete('ifx_oidc_state');
    res.cookies.delete('ifx_oidc_verifier');
    res.cookies.delete('ifx_oidc_require_role');

    return res;

  } catch (err) {
    console.error('SSO callback error:', err);
    return NextResponse.redirect(new URL('/?error=callback_error', request.url));
  }
}
