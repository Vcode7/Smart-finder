// src/middleware.ts / src/proxy.ts
// Next.js edge middleware — protects all routes except /auth/* and /api/auth/*

import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, COOKIE_NAME } from '@/lib/auth/jwt';

const PUBLIC_PATHS = [
  '/auth/login',
  '/auth/signup',
  '/api/auth/login',
  '/api/auth/signup',
  '/api/auth/logout',
  '/_next',
  '/favicon.ico',
];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Allow static files
  if (pathname.match(/\.(png|jpg|jpeg|svg|gif|webp|ico|css|js|woff2?)$/)) {
    return NextResponse.next();
  }

  // Allow all /api/* requests to pass directly to the Python backend
  if (pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;

  if (!token) {
    if (pathname.startsWith('/api/')) {
      return new NextResponse(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return NextResponse.redirect(new URL('/auth/login', req.url));
  }

  const payload = verifyToken(token);
  if (!payload) {
    if (pathname.startsWith('/api/')) {
      return new NextResponse(JSON.stringify({ error: 'Unauthorized — invalid token' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const res = NextResponse.redirect(new URL('/auth/login', req.url));
    res.cookies.delete(COOKIE_NAME);
    return res;
  }

  // Admin-only paths — enforce on middleware level
  if (pathname.startsWith('/admin') || pathname.startsWith('/api/admin')) {
    if (payload.role !== 'admin') {
      if (pathname.startsWith('/api/')) {
        return new NextResponse(JSON.stringify({ error: 'Forbidden' }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return NextResponse.redirect(new URL('/', req.url));
    }
  }

  // For file upload and search endpoints, pass through directly to avoid request body stream rewriting/truncation
  if (
    pathname.startsWith('/api/knowledge/upload') ||
    pathname.startsWith('/api/search/multimodal') ||
    pathname.startsWith('/api/search/smart') ||
    pathname.startsWith('/api/search/face')
  ) {
    return NextResponse.next();
  }

  // Inject user info into request headers for downstream use
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set('x-user-id', payload.userId);
  requestHeaders.set('x-user-role', payload.role);
  requestHeaders.set('x-user-email', payload.email);

  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};

export default proxy;
export { proxy as middleware };
