export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {'Content-Type': 'application/json', ...options.headers},
  });
  const body = await response.json();
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : 'Check the URL and title, then try again.';
    throw new Error(detail);
  }
  return body;
}
