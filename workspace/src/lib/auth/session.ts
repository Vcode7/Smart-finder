// src/lib/auth/session.ts
// Server-side helper to get the current user from a Next.js request

import { cookies } from 'next/headers';
import { verifyToken, COOKIE_NAME, type JWTPayload } from './jwt';
import { dbGet } from '@/lib/db/client';

export interface AuthUser {
  id: string;
  email: string;
  username: string;
  role: 'user' | 'admin';
}

/**
 * Reads the JWT cookie from the request and returns the current user.
 * Returns null if unauthenticated or token is invalid.
 */
export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get(COOKIE_NAME)?.value;
    if (!token) return null;

    const payload = verifyToken(token);
    if (!payload) return null;

    // Verify user still exists in DB
    const user = dbGet<AuthUser>(
      'SELECT id, email, username, role FROM users WHERE id = ?',
      [payload.userId]
    );
    return user ?? null;
  } catch {
    return null;
  }
}

/**
 * Requires authentication. Returns 401 response if not authenticated.
 */
export async function requireAuth(): Promise<AuthUser | Response> {
  const user = await getCurrentUser();
  if (!user) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  return user;
}

/**
 * Requires admin role. Returns 401/403 if not authorized.
 */
export async function requireAdmin(): Promise<AuthUser | Response> {
  const result = await requireAuth();
  if (result instanceof Response) return result;
  if (result.role !== 'admin') {
    return new Response(JSON.stringify({ error: 'Forbidden — Admin only' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  return result;
}

export function isResponse(val: unknown): val is Response {
  return val instanceof Response;
}
