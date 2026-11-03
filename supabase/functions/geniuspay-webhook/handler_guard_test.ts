import { callSupabaseRpc } from "./supabase_rpc.ts";
import {
  createGeniusPayWebhookHandler,
  hmacHex,
  phpJsonEncode,
  type WebhookRpcArgs,
} from "./handler.ts";

// Tests des branches de GARDE non couvertes par handler_test.ts :
// corps trop volumineux, JSON invalide, champs de paiement invalides,
// metadonnees manquantes, et chemins d erreur de callSupabaseRpc.
// Aucun reseau : Supabase et l horloge sont remplaces par des fakes.

const FIXED_TIME = 1_800_000_000;
const WEBHOOK_SECRET = "test-only-geniuspay-webhook-secret";

type ProcessEventResult = {
  data: Record<string, unknown> | null;
  error: { code?: string } | null;
};

function validPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: "evt_guard_0001",
    event: "payment.success",
    environment: "sandbox",
    timestamp: FIXED_TIME,
    data: {
      amount: 2500,
      currency: "XOF",
      status: "completed",
      reference: "GP-GUARD-0001",
      metadata: { order_id: "FW-GUARD-0001" },
    },
    ...overrides,
  };
}

function makeHandler(
  processEvent: (args: WebhookRpcArgs) => Promise<ProcessEventResult> =
    async () => ({
      data: { duplicate: false, payment_status: "succeeded", order_status: "paid" },
      error: null,
    }),
) {
  return createGeniusPayWebhookHandler({
    getEnv: (name) =>
      name === "GENIUSPAY_WEBHOOK_SECRET" ? WEBHOOK_SECRET : undefined,
    nowSeconds: () => FIXED_TIME,
    processEvent,
  });
}

async function signedRequest(
  payload: Record<string, unknown>,
  headerOverrides: Record<string, string> = {},
  validSignature = true,
): Promise<Request> {
  const timestamp = String(payload.timestamp ?? FIXED_TIME);
  const rawBody = JSON.stringify(payload);
  const signature = validSignature
    ? await hmacHex(WEBHOOK_SECRET, timestamp + "." + phpJsonEncode(payload))
    : "0".repeat(64);
  return new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Webhook-Signature": "sha256=" + signature,
      "X-Webhook-Timestamp": timestamp,
      "X-Webhook-Event": String(payload.event ?? "payment.success"),
      "X-Webhook-Environment": String(payload.environment ?? "sandbox"),
      ...headerOverrides,
    },
    body: rawBody,
  });
}

Deno.test("rejette un corps trop volumineux (HTTP 413) sans appeler la persistance", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const grosCorps = "x".repeat(64 * 1024 + 1);
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Webhook-Signature": "sha256=" + "0".repeat(64),
      "X-Webhook-Timestamp": String(FIXED_TIME),
      "X-Webhook-Event": "payment.success",
      "X-Webhook-Environment": "sandbox",
    },
    body: grosCorps,
  }));
  if (response.status !== 413) throw new Error("Attendu HTTP 413, obtenu " + response.status);
  if (called) throw new Error("La persistance ne doit pas etre appelee pour un corps trop volumineux");
});

Deno.test("rejette un corps JSON invalide (HTTP 400)", async () => {
  const handler = makeHandler();
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Webhook-Signature": "sha256=" + "0".repeat(64),
      "X-Webhook-Timestamp": String(FIXED_TIME),
      "X-Webhook-Event": "payment.success",
      "X-Webhook-Environment": "sandbox",
    },
    body: "{ceci n est pas du json",
  }));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
});

Deno.test("rejette un corps JSON qui n est pas un objet (HTTP 400)", async () => {
  const handler = makeHandler();
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Webhook-Signature": "sha256=" + "0".repeat(64),
      "X-Webhook-Timestamp": String(FIXED_TIME),
      "X-Webhook-Event": "payment.success",
      "X-Webhook-Environment": "sandbox",
    },
    body: "[1, 2, 3]",
  }));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
});

Deno.test("rejette payment.success si le statut fournisseur n est pas completed (HTTP 400)", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const payload = validPayload({ data: { amount: 2500, currency: "XOF", status: "pending", reference: "GP-GUARD-0002", metadata: { order_id: "FW-GUARD-0002" } } });
  const response = await handler(await signedRequest(payload));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
  if (called) throw new Error("Un payment.success non completed ne doit jamais atteindre la persistance");
});

Deno.test("rejette une devise invalide (HTTP 400)", async () => {
  const handler = makeHandler();
  const payload = validPayload({ data: { amount: 2500, currency: "EURO", status: "completed", reference: "GP-GUARD-0003", metadata: { order_id: "FW-GUARD-0003" } } });
  const response = await handler(await signedRequest(payload));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
});

Deno.test("rejette un montant nul ou negatif (HTTP 400)", async () => {
  const handler = makeHandler();
  const payload = validPayload({ data: { amount: 0, currency: "XOF", status: "completed", reference: "GP-GUARD-0004", metadata: { order_id: "FW-GUARD-0004" } } });
  const response = await handler(await signedRequest(payload));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
});

Deno.test("rejette un paiement sans metadonnees de commande (HTTP 400)", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const payload = validPayload({ data: { amount: 2500, currency: "XOF", status: "completed", reference: "GP-GUARD-0005" } });
  const response = await handler(await signedRequest(payload));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
  if (called) throw new Error("Un paiement sans metadonnees ne doit pas atteindre la persistance");
});

Deno.test("rejette un paiement sans objet data (HTTP 400)", async () => {
  const handler = makeHandler();
  const payload = validPayload({ data: null });
  const response = await handler(await signedRequest(payload));
  if (response.status !== 400) throw new Error("Attendu HTTP 400, obtenu " + response.status);
});

Deno.test("callSupabaseRpc refuse une configuration vide (INVALID_RPC_CONFIGURATION)", async () => {
  const result = await callSupabaseRpc("", "sb_secret_x", "fn", {}, false, async () => {
    throw new Error("ne doit pas etre appele");
  });
  if (result.error?.code !== "INVALID_RPC_CONFIGURATION") {
    throw new Error("Attendu INVALID_RPC_CONFIGURATION, obtenu " + result.error?.code);
  }
});

Deno.test("callSupabaseRpc refuse un nom de fonction invalide (INVALID_RPC_CONFIGURATION)", async () => {
  const result = await callSupabaseRpc("https://project.supabase.co", "sb_secret_x", "fn; drop", {}, false, async () => {
    throw new Error("ne doit pas etre appele");
  });
  if (result.error?.code !== "INVALID_RPC_CONFIGURATION") {
    throw new Error("Attendu INVALID_RPC_CONFIGURATION, obtenu " + result.error?.code);
  }
});

Deno.test("callSupabaseRpc capture le code d erreur JSON d une reponse 400", async () => {
  const result = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_x",
    "shoplinous_process_geniuspay_webhook",
    { p_event_id: "evt_1" },
    false,
    async () => new Response(JSON.stringify({ code: "23514", message: "check" }), { status: 400 }),
  );
  if (result.error?.code !== "23514") throw new Error("Attendu 23514, obtenu " + result.error?.code);
  if (result.data !== null) throw new Error("Aucune donnee ne doit etre renvoyee en cas d erreur");
});

Deno.test("callSupabaseRpc renvoie une erreur sans code si la reponse est illisible", async () => {
  const result = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_x",
    "shoplinous_process_geniuspay_webhook",
    { p_event_id: "evt_1" },
    false,
    async () => new Response("pas du json", { status: 500 }),
  );
  if (result.error === null || result.error.code) {
    throw new Error("Attendu une erreur sans code, obtenu " + JSON.stringify(result.error));
  }
});

Deno.test("callSupabaseRpc degrade proprement en cas d erreur reseau (NETWORK_ERROR)", async () => {
  const result = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_x",
    "shoplinous_process_geniuspay_webhook",
    { p_event_id: "evt_1" },
    false,
    async () => { throw new Error("network down"); },
  );
  if (result.error?.code !== "NETWORK_ERROR") {
    throw new Error("Attendu NETWORK_ERROR, obtenu " + result.error?.code);
  }
});

Deno.test("callSupabaseRpc accepte une reponse tableau a un element, refuse deux (INVALID_RPC_RESPONSE)", async () => {
  const unique = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_x",
    "fn",
    {},
    false,
    async () => Response.json([{ duplicate: false }]),
  );
  if (unique.error || unique.data?.duplicate !== false) {
    throw new Error("Attendu le premier element du tableau");
  }
  const multiple = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_x",
    "fn",
    {},
    false,
    async () => Response.json([{ duplicate: false }, { duplicate: true }]),
  );
  if (multiple.error?.code !== "INVALID_RPC_RESPONSE") {
    throw new Error("Attendu INVALID_RPC_RESPONSE pour un tableau multiple, obtenu " + multiple.error?.code);
  }
});
