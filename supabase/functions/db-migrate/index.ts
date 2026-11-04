// Fonction temporaire protegee : execute du SQL de migration pour le
// deploiement CI (le token Management utilise n'a pas la permission
// database_read). Gardee par le secret DB_MIGRATE_TOKEN ; desactivee en
// fin de deploiement. Aucune donnee personnelle n'est exposee.

import postgres from "npm:postgres@3.4.5";

const DB_URL = Deno.env.get("SUPABASE_DB_URL");
const TOKEN = Deno.env.get("DB_MIGRATE_TOKEN");

function reply(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") {
    return reply({ ok: false, error: "method_not_allowed" }, 405);
  }
  let body: unknown = null;
  try {
    body = await request.json();
  } catch (_) {
    return reply({ ok: false, error: "invalid_json" }, 400);
  }
  const src = (body ?? {}) as Record<string, unknown>;
  if (!TOKEN || typeof src.token !== "string" || src.token !== TOKEN) {
    return reply({ ok: false, error: "unauthorized" }, 401);
  }
  if (typeof src.sql !== "string" || src.sql.trim().length === 0) {
    return reply({ ok: false, error: "missing_sql" }, 400);
  }
  if (src.sql.length > 200000) {
    return reply({ ok: false, error: "sql_too_large" }, 413);
  }
  if (!DB_URL) {
    return reply({ ok: false, error: "db_url_unavailable" }, 503);
  }
  const sql = postgres(DB_URL, {
    max: 1,
    idle_timeout: 5,
    connect_timeout: 15,
    prepare: false,
  });
  try {
    const rows = await sql.unsafe(src.sql);
    const data = Array.isArray(rows)
      ? rows.slice(0, 50).map((r: Record<string, unknown>) => r)
      : [];
    return reply({ ok: true, rows: data, row_count: Array.isArray(rows) ? rows.length : 0 });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return reply({ ok: false, error: message.slice(0, 400) }, 400);
  } finally {
    await sql.end({ timeout: 5 }).catch(() => {});
  }
});
