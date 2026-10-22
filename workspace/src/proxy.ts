// src/proxy.ts — Next.js 16 proxy (formerly middleware)
// Guards app pages: unauthenticated visitors are sent to /auth/login and /admin is
// limited to admins. /api/* is excluded by the matcher: those requests are rewritten
// to the Python backend, which authenticates every route itself. Keeping the proxy
// off /api also stops Next from cloning (and size-capping) request bodies.

import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, COOKIE_NAME } from '@/lib/auth/jwt';

const PUBLIC_PATHS = ['/auth/login', '/auth/signup', '/auth/admin-signup', '/_next', '/favicon.ico'];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Static files
  if (pathname.match(/\.(png|jpg|jpeg|svg|gif|webp|ico|css|js|woff2?)$/)) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (!token) {
    return NextResponse.redirect(new URL('/auth/login', req.url));
  }

  const payload = verifyToken(token);
  if (!payload) {
    const res = NextResponse.redirect(new URL('/auth/login', req.url));
    res.cookies.delete(COOKIE_NAME);
    return res;
  }

  if (pathname.startsWith('/admin') && payload.role !== 'admin') {
    return NextResponse.redirect(new URL('/', req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api/|_next/static|_next/image|favicon.ico).*)'],
};

export default proxy;
