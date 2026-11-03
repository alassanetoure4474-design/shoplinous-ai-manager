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

Deno.test("uses a deterministic PHP-compatible JSON serialization for HMAC", () => {
  const serialized = phpJsonEncode({ message: "café/été", value: 1 });
  if (serialized !== '{"message":"caf\\u00e9\\/\\u00e9t\\u00e9","value":1}') {
    throw new Error("Unexpected canonical serialization: " + serialized);
  }
});
