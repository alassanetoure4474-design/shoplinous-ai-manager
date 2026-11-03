import { callSupabaseRpc } from "./supabase_rpc.ts";
import {
  createGeniusPayWebhookHandler,
  hmacHex,
  phpJsonEncode,
  type WebhookRpcArgs,
} from "./handler.ts";

const FIXED_TIME = 1_800_000_000;
const WEBHOOK_SECRET = "test-only-geniuspay-webhook-secret";

function validPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: "evt_test_0001",
    event: "payment.success",
    environment: "sandbox",
    timestamp: FIXED_TIME,
    data: {
      amount: 2500,
      currency: "XOF",
      status: "completed",
      reference: "GP-TEST-0001",
      metadata: { order_id: "FW-TEST-0001" },
    },
    ...overrides,
  };
}

async function makeRequest(
  payload: Record<string, unknown> = validPayload(),
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

function makeHandler(
  processEvent: (args: WebhookRpcArgs) => Promise<{
    data: Record<string, unknown> | null;
    error: { code?: string } | null;
  }> = async () => ({
    data: { duplicate: false, payment_status: "succeeded", order_status: "paid" },
    error: null,
  }),
) {
  return createGeniusPayWebhookHandler({
    getEnv: (name) => name === "GENIUSPAY_WEBHOOK_SECRET" ? WEBHOOK_SECRET : undefined,
    nowSeconds: () => FIXED_TIME,
    processEvent,
  });
}

Deno.test("accepts a valid signed Sandbox payment.success and forwards verified fields", async () => {
  let received: WebhookRpcArgs | undefined;
  const handler = makeHandler(async (args) => {
    received = args;
    return {
      data: { duplicate: false, payment_status: "succeeded", order_status: "paid" },
      error: null,
    };
  });

  const response = await handler(await makeRequest());
  const body = await response.json();

  if (response.status !== 200) throw new Error("Expected HTTP 200, got " + response.status);
  if (body.received !== true || body.duplicate !== false) throw new Error("Unexpected response");
  if (!received) throw new Error("Supabase RPC was not called");
  if (received.p_reference !== "GP-TEST-0001") throw new Error("Wrong provider reference");
  if (received.p_order_number !== "FW-TEST-0001") throw new Error("Wrong order number");
  if (received.p_amount !== 2500 || received.p_currency !== "XOF") {
    throw new Error("Wrong amount or currency forwarded to RPC");
  }
  if (received.p_environment !== "sandbox") throw new Error("Non-Sandbox environment forwarded");
});

Deno.test("rejects an invalid HMAC signature without calling persistence", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });

  const response = await handler(await makeRequest(validPayload(), {}, false));
  if (response.status !== 401) throw new Error("Expected HTTP 401, got " + response.status);
  if (called) throw new Error("Persistence must not be called for an invalid signature");
});

Deno.test("rejects a webhook timestamp older than the 300-second window", async () => {
  const payload = validPayload({ timestamp: FIXED_TIME - 301 });
  const handler = makeHandler();
  const response = await handler(await makeRequest(payload));
  if (response.status !== 401) throw new Error("Expected HTTP 401, got " + response.status);
});

Deno.test("rejects a mismatch between event header and signed payload", async () => {
  const handler = makeHandler();
  const response = await handler(await makeRequest(validPayload(), {
    "X-Webhook-Event": "payment.failed",
  }));
  if (response.status !== 400) throw new Error("Expected HTTP 400, got " + response.status);
});

Deno.test("rejects Live webhooks even when the HMAC is valid", async () => {
  const payload = validPayload({ environment: "live" });
  const handler = makeHandler();
  const response = await handler(await makeRequest(payload));
  if (response.status !== 403) throw new Error("Expected HTTP 403, got " + response.status);
});

Deno.test("returns duplicate=true when the database reports an already processed event", async () => {
  const handler = makeHandler(async () => ({
    data: { duplicate: true, payment_status: "succeeded", order_status: "paid" },
    error: null,
  }));
  const response = await handler(await makeRequest());
  const body = await response.json();
  if (response.status !== 200 || body.duplicate !== true) {
    throw new Error("Expected an acknowledged duplicate");
  }
});

Deno.test("returns HTTP 400 for a permanent SQL validation mismatch", async () => {
  const handler = makeHandler(async () => ({
    data: null,
    error: { code: "23514" },
  }));
  const response = await handler(await makeRequest());
  if (response.status !== 400) throw new Error("Expected HTTP 400, got " + response.status);
});

Deno.test("returns HTTP 503 for transient persistence errors so GeniusPay can retry", async () => {
  const handler = makeHandler(async () => ({
    data: null,
    error: { code: "08006" },
  }));
  const response = await handler(await makeRequest());
  if (response.status !== 503) throw new Error("Expected HTTP 503, got " + response.status);
});


Deno.test("acknowledges a signed GeniusPay webhook.test without touching payment persistence", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const payload = {
    id: "evt_webhook_test_0001",
    event: "webhook.test",
    environment: "sandbox",
    timestamp: FIXED_TIME,
  };
  const response = await handler(await makeRequest(payload));
  const body = await response.json();
  if (response.status !== 200 || body.test !== true || body.received !== true) {
    throw new Error("Expected an acknowledged webhook.test event");
  }
  if (called) throw new Error("A test event must not call payment persistence");
});

Deno.test("acknowledges GeniusPay dashboard webhook.test probes without signature headers", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const payload = {
    id: "evt_dashboard_test_0001",
    event: "webhook.test",
    environment: "sandbox",
    timestamp: FIXED_TIME,
  };
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  }));
  const body = await response.json();
  if (response.status !== 200 || body.received !== true || body.test !== true) {
    throw new Error("Expected the unsigned dashboard test probe to be acknowledged");
  }
  if (body.signature_verified !== false) {
    throw new Error("Dashboard test response must disclose that no HMAC was verified");
  }
  if (called) throw new Error("A dashboard test probe must never call payment persistence");
});

Deno.test("rejects unsigned payment events even when the dashboard test probe is allowed", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(validPayload()),
  }));
  if (response.status !== 400) throw new Error("Expected HTTP 400, got " + response.status);
  if (called) throw new Error("Unsigned payment events must never reach persistence");
});

Deno.test("acknowledges signed payment.initiated without persisting an order update", async () => {
  let called = false;
  const handler = makeHandler(async () => {
    called = true;
    return { data: null, error: null };
  });
  const payload = validPayload({ event: "payment.initiated" });
  const response = await handler(await makeRequest(payload));
  const body = await response.json();
  if (response.status !== 200 || body.ignored !== true) {
    throw new Error("Expected payment.initiated to be acknowledged as ignored");
  }
  if (called) throw new Error("payment.initiated must not mutate payment persistence");
});

Deno.test("rejects non-POST methods", async () => {
  const handler = makeHandler();
  const response = await handler(new Request("https://local.test/geniuspay-webhook", {
    method: "GET",
  }));
  if (response.status !== 405) throw new Error("Expected HTTP 405, got " + response.status);
});

Deno.test("rejects missing webhook secrets without accessing persistence", async () => {
  let called = false;
  const handler = createGeniusPayWebhookHandler({
    getEnv: () => undefined,
    nowSeconds: () => FIXED_TIME,
    processEvent: async () => {
      called = true;
      return { data: null, error: null };
    },
  });
  const response = await handler(await makeRequest());
  if (response.status !== 503) throw new Error("Expected HTTP 503, got " + response.status);
  if (called) throw new Error("Persistence must not be called without a webhook secret");
});


Deno.test("uses a Supabase sb_secret key only in the apikey header", async () => {
  let capturedHeaders: Headers | undefined;
  const result = await callSupabaseRpc(
    "https://project.supabase.co",
    "sb_secret_test_only",
    "shoplinous_process_geniuspay_webhook",
    { p_event_id: "evt_1" },
    false,
    async (_input, init) => {
      capturedHeaders = new Headers(init?.headers);
      return Response.json({ duplicate: false, payment_status: "succeeded" });
    },
  );
  if (result.error || result.data?.payment_status !== "succeeded") {
    throw new Error("Expected the mocked Supabase RPC response");
  }
  if (capturedHeaders?.get("apikey") !== "sb_secret_test_only") {
    throw new Error("Supabase secret key was not sent in apikey");
  }
  if (capturedHeaders?.has("authorization")) {
    throw new Error("A non-JWT Supabase secret key must not be sent as Bearer");
  }
});

Deno.test("keeps the Bearer header for legacy service_role JWT keys", async () => {
  let capturedHeaders: Headers | undefined;
  const legacyJwt = "eyJhbGciOiJIUzI1NiJ9.legacy.signature";
  await callSupabaseRpc(
    "https://project.supabase.co",
    legacyJwt,
    "shoplinous_process_geniuspay_webhook",
    { p_event_id: "evt_1" },
    true,
    async (_input, init) => {
      capturedHeaders = new Headers(init?.headers);
      return Response.json({ duplicate: false });
    },
  );
  if (capturedHeaders?.get("authorization") !== "Bearer " + legacyJwt) {
    throw new Error("Legacy service_role JWT lost its Bearer header");
  }
});

Deno.test("uses a deterministic PHP-compatible JSON serialization for HMAC", () => {
  const serialized = phpJsonEncode({ message: "café/été", value: 1 });
  if (serialized !== '{"message":"caf\\u00e9\\/\\u00e9t\\u00e9","value":1}') {
    throw new Error("Unexpected canonical serialization: " + serialized);
  }
});
