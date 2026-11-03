import { createClient } from "npm:@supabase/supabase-js@2";
import {
  createGeniusPayWebhookHandler,
  type WebhookRpcArgs,
} from "./handler.ts";

function getSupabaseSecretKey(): string {
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;

  const encoded = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (!encoded) return "";
  try {
    const keys = JSON.parse(encoded);
    if (keys && typeof keys === "object") {
      if (typeof keys.default === "string") return keys.default;
      const first = Object.values(keys).find((value) => typeof value === "string");
      return typeof first === "string" ? first : "";
    }
  } catch {
    return "";
  }
  return "";
}

const handler = createGeniusPayWebhookHandler({
  getEnv: (name) => Deno.env.get(name),
  nowSeconds: () => Math.floor(Date.now() / 1000),
  processEvent: async (args: WebhookRpcArgs) => {
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const supabaseKey = getSupabaseSecretKey();
    if (!supabaseUrl || !supabaseKey) {
      return { data: null, error: { code: "CONFIGURATION_MISSING" } };
    }
    const supabase = createClient(supabaseUrl, supabaseKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    return await supabase.rpc("shoplinous_process_geniuspay_webhook", args);
  },
});

Deno.serve(handler);
