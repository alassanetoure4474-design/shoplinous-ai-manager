export type RpcError = { code?: string };
export type RpcResult = {
  data: Record<string, unknown> | null;
  error: RpcError | null;
};

type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

/**
 * Calls a PostgREST RPC without leaking a Supabase secret key into a Bearer
 * header. New sb_secret_* keys are sent only as apikey. Legacy JWT keys keep
 * the Authorization header for backwards compatibility.
 */
export async function callSupabaseRpc(
  supabaseUrl: string,
  apiKey: string,
  functionName: string,
  args: Record<string, unknown>,
  legacyJwtKey: boolean,
  fetcher: FetchLike = fetch,
): Promise<RpcResult> {
  if (!supabaseUrl || !apiKey || !/^[a-z0-9_]+$/i.test(functionName)) {
    return { data: null, error: { code: "INVALID_RPC_CONFIGURATION" } };
  }

  const headers: Record<string, string> = {
    apikey: apiKey,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (legacyJwtKey) {
    headers.Authorization = "Bearer " + apiKey;
  }

  try {
    const response = await fetcher(
      supabaseUrl.replace(/\/$/, "") + "/rest/v1/rpc/" + functionName,
      {
        method: "POST",
        headers,
        body: JSON.stringify(args),
      },
    );

    if (!response.ok) {
      let code: string | undefined;
      try {
        const problem = await response.json();
        if (
          problem &&
          typeof problem === "object" &&
          typeof problem.code === "string"
        ) {
          code = problem.code;
        }
      } catch {
        // Do not expose the response body; it may contain private details.
      }
      return { data: null, error: code ? { code } : {} };
    }

    const parsed: unknown = await response.json();
    const result = Array.isArray(parsed)
      ? (parsed.length === 1 ? parsed[0] : null)
      : parsed;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      return { data: null, error: { code: "INVALID_RPC_RESPONSE" } };
    }
    return { data: result as Record<string, unknown>, error: null };
  } catch {
    return { data: null, error: { code: "NETWORK_ERROR" } };
  }
}
