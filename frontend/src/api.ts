export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (e: { loc?: string[]; msg: string }) =>
                  `${e.loc?.slice(1).join(".")}: ${e.msg}`,
              )
              .join("; ")
          : `Сервер вернул ошибку ${response.status}`;
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
