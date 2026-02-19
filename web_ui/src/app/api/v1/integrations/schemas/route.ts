import { NextRequest, NextResponse } from 'next/server';
import { getConfigServiceBaseUrl, getUpstreamAuthHeaders } from '../../../_utils/upstream';

export async function GET(request: NextRequest) {
  const authHeaders = getUpstreamAuthHeaders(request);
  if (!Object.keys(authHeaders).length) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const baseUrl = getConfigServiceBaseUrl();
    const searchParams = request.nextUrl.searchParams;
    const queryString = searchParams.toString();
    const url = `${baseUrl}/api/v1/integrations/schemas${queryString ? `?${queryString}` : ''}`;

    const res = await fetch(url, {
      headers: {
        ...authHeaders,
        'Content-Type': 'application/json',
      },
    });

    if (!res.ok) {
      const text = await res.text();
      console.error('Config service error:', res.status, text);
      return NextResponse.json({ error: text }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('Failed to fetch integration schemas:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
