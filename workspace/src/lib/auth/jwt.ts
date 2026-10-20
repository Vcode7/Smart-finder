// src/lib/auth/jwt.ts
// JWT signing and verification using jsonwebtoken

import jwt from 'jsonwebtoken';

// Must equal JWT_SECRET in backend/.env: the backend signs the session cookie and this
// proxy verifies it. There is deliberately no fallback secret.
const JWT_SECRET = process.env.JWT_SECRET || '';
const JWT_EXPIRES_IN = '7d';

if (!JWT_SECRET) {
  console.error('[auth] JWT_SECRET is not set in workspace/.env — every session will be rejected. Copy the value from backend/.env.');
}

export interface JWTPayload {
  userId: string;
  email: string;
  username: string;
  role: 'user' | 'admin';
  iat?: number;
  exp?: number;
}

export function signToken(payload: Omit<JWTPayload, 'iat' | 'exp'>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN });
}

export function verifyToken(token: string): JWTPayload | null {
  if (!JWT_SECRET) return null;
  try {
    return jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] }) as JWTPayload;
  } catch {
    return null;
  }
}

export const COOKIE_NAME = 'sf_auth';
export const COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax' as const,
  path: '/',
  maxAge: 60 * 60 * 24 * 7, // 7 days in seconds
};
