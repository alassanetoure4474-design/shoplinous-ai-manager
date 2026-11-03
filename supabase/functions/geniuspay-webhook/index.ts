import {
  createGeniusPayWebhookHandler,
  type WebhookRpcArgs,
} from "./handler.ts";
import { callSupabaseRpc } from "./supabase_rpc.ts";

type SupabaseCredentials = {
  key: string;
  legacyJwtKey: boolean;
};

function getSupabaseCredentials(): SupabaseCredentials {
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) {
    return { key: legacy, legacyJwtKey: true };
  }

  const singleSecret = Deno.env.get("SUPABASE_SECRET_KEY");
  if (singleSecret) {
    return { key: singleSecret, legacyJwtKey: false };
  }

  const encoded = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (!encoded) return { key: "", legacyJwtKey: false };
  try {
    const keys = JSON.parse(encoded);
    if (
      keys &&
      typeof keys === "object" &&
      typeof keys.default === "string"
    ) {
      return { key: keys.default, legacyJwtKey: false };
    }
  } catch {
    return { key: "", legacyJwtKey: false };
  }
  return { key: "", legacyJwtKey: false };
}

const handler = createGeniusPayWebhookHandler({
  getEnv: (name) => Deno.env.get(name),
  nowSeconds: () => Math.floor(Date.now() / 1000),
  processEvent: async (args: WebhookRpcArgs) => {
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const credentials = getSupabaseCredentials();
    if (!supabaseUrl || !credentials.key) {
      return { data: null, error: { code: "CONFIGURATION_MISSING" } };
    }
    return await callSupabaseRpc(
      supabaseUrl,
      credentials.key,
      "shoplinous_process_geniuspay_webhook",
      args,
      credentials.legacyJwtKey,
    );
  },
});

Deno.serve(handler);
