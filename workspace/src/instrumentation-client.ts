// Runs in the browser before the app's code. Next's basePath does not prefix fetch(), so add
// it here to every root-relative /api call (api(), jsonRequest(), postSettings(), ...).
const base = process.env.NEXT_PUBLIC_BASE_PATH || '';
if (base) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) =>
    nativeFetch(typeof input === 'string' && input.startsWith('/api/') ? base + input : input, init);
}
