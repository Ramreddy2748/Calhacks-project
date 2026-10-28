export async function api(path, options) {
  let response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The connection timed out. Check the backend and retry.');
    throw new Error('Unable to reach the backend. Check your connection and retry.');
  }
  const body = await response.json().catch(() => null);
  const fail = message => { throw Object.assign(new Error(message), { status: response.status }); };
  if (!response.ok) {
    if (typeof body?.detail === 'string') fail(body.detail);
    if (response.status >= 500) fail('The backend is unavailable. Start the backend, then retry.');
    if (response.status === 401) fail('Sign in to this workspace to continue.');
    fail('The request failed. Please retry.');
  }
  if (body === null) fail('The backend returned an empty or invalid response. Check the backend and retry.');
  return body;
}
