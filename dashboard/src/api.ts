export async function request(
  path: string,
  options?: RequestInit,
): Promise<Response> {
  return fetch(`/admin/api/${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
    ...options,
  });
}
