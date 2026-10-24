// Path prefix the app is served under (NEXT_BASE_PATH at build time; empty = root).
// For <img src> and <a href> addresses, which neither Next nor the fetch() hook prefixes.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || '';
export const withBase = (url: string) => (url.startsWith('/') && !url.startsWith('//') ? BASE_PATH + url : url);
