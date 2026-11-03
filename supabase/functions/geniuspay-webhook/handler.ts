const encoder = new TextEncoder();
const MAX_BODY_BYTES = 64 * 1024;
const WEBHOOK_WINDOW_SECONDS = 300;
const ALLOWED_EVENTS = new Set([
  "payment.success",
  "payment.failed",
  "payment.cancelled",
  "payment.expired",
  "payment.refunded",
  "payment.initiated",
  "webhook.test",
]);

export type WebhookRpcArgs = {
  p_event_id: string;
  p_delivery_id: string | null;
  p_reference: string;
  p_event_type: string;
  p_environment: string;
  p_amount: number;
  p_currency: string;
  p_order_number: string;
  p_provider_status: string;
  p_payload_sha256: string;
};

type RpcError = { code?: string };
type WebhookDependencies = {
  getEnv: (name: string) => string | undefined;
  nowSeconds: () => number;
  processEvent: (args: WebhookRpcArgs) => Promise<{
    data: Record<string, unknown> | null;
    error: RpcError | null;
  }>;
};

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

export async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(message),
  );
  return bytesToHex(signature);
}

export function phpJsonEncode(value: unknown): string {
  // GeniusPay documents PHP json_encode($payload): compact JSON, escaped
  // forward slashes and escaped non-ASCII code units.
  const compact = JSON.stringify(value);
  if (compact === undefined) {
    throw new Error("Webhook payload cannot be serialized");
  }
  return compact
    .replace(/\//g, "\\/")
    .replace(/[\u007f-\uffff]/g, (character) =>
      "\\u" + character.charCodeAt(0).toString(16).padStart(4, "0")
    );

}

async function sha256Hex(value: string): Promise<string> {
  return bytesToHex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

/**
 * Creates a testable HTTP handler. Production dependencies (environment,
 * clock, and Supabase RPC) are injected by index.ts; tests use deterministic
 * fakes and never connect to a real Supabase project.
 */
export function createGeniusPayWebhookHandler(
  dependencies: WebhookDependencies,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    if (request.method !== "POST") {
      return jsonResponse(405, { error: "method_not_allowed" });
    }

    const webhookSecret = dependencies.getEnv("GENIUSPAY_WEBHOOK_SECRET") ?? "";
    if (!webhookSecret) {
      return jsonResponse(503, { error: "webhook_not_configured" });
    }

    const signatureHeader = request.headers.get("X-Webhook-Signature") ?? "";
    const timestampHeader = request.headers.get("X-Webhook-Timestamp") ?? "";
    const eventHeader = request.headers.get("X-Webhook-Event") ?? "";
    const environmentHeader = request.headers.get("X-Webhook-Environment") ?? "";
    const deliveryHeader = request.headers.get("X-Webhook-Delivery");

    let rawBody: string;
    try {
      rawBody = await request.text();
    } catch {
      return jsonResponse(400, { error: "webhook_body_unreadable" });
    }
    if (encoder.encode(rawBody).byteLength > MAX_BODY_BYTES) {
      return jsonResponse(413, { error: "webhook_body_too_large" });
    }

    let payload: Record<string, unknown>;
    try {
      const parsed = JSON.parse(rawBody);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return jsonResponse(400, { error: "invalid_webhook_payload" });
      }
      payload = parsed as Record<string, unknown>;
    } catch {
      return jsonResponse(400, { error: "invalid_webhook_json" });
    }

    const payloadEvent = typeof payload.event === "string" ? payload.event : "";
    const payloadEnvironment = typeof payload.environment === "string"
      ? payload.environment.toLowerCase()
      : "";
    const payloadTimestamp = Number(payload.timestamp);
    const now = dependencies.nowSeconds();

    if (!signatureHeader || !timestampHeader) {
      const allSignatureHeadersMissing =
        !signatureHeader && !timestampHeader;
      const dashboardTestEvent =
        payloadEvent === "webhook.test" ||
        payload.type === "webhook.test" ||
        payload.event_type === "webhook.test" ||
        payload.test === true;
      const validDashboardTest =
        allSignatureHeadersMissing &&
        dashboardTestEvent &&
        (!payloadEnvironment || payloadEnvironment === "sandbox");

      // GeniusPay's dashboard tester sends a body-only test probe whose
      // envelope may omit the optional id/timestamp fields or use "type".
      // A Sandbox webhook.test probe has no payment side effects; all payment
      // events still require every signature header and a valid HMAC below.
      if (validDashboardTest) {
        return jsonResponse(200, {
          received: true,
          test: true,
          signature_verified: false,
        });
      }
      return jsonResponse(400, { error: "missing_webhook_headers" });
    }

    const timestamp = Number(timestampHeader);
    if (!Number.isSafeInteger(timestamp) || Math.abs(now - timestamp) > WEBHOOK_WINDOW_SECONDS) {
      return jsonResponse(401, { error: "webhook_timestamp_invalid_or_expired" });
    }
    const missingEventEnvironmentHeaders = !eventHeader || !environmentHeader;
    if (
      !payloadEvent ||
      !ALLOWED_EVENTS.has(payloadEvent) ||
      (eventHeader && payloadEvent !== eventHeader) ||
      !payloadEnvironment ||
      (environmentHeader && payloadEnvironment !== environmentHeader.toLowerCase()) ||
      (missingEventEnvironmentHeaders && payloadEvent !== "webhook.test") ||
      !Number.isSafeInteger(payloadTimestamp) ||
      payloadTimestamp !== timestamp
    ) {
      return jsonResponse(400, { error: "webhook_headers_payload_mismatch" });
    }
    if (payloadEnvironment !== "sandbox") {
      return jsonResponse(403, { error: "live_webhooks_disabled" });
    }

    const providedSignature = signatureHeader.trim().replace(/^sha256=/i, "").toLowerCase();
    let canonicalPayload = "";
    let signatureIsValid = false;
    try {
      canonicalPayload = phpJsonEncode(payload);
      const [phpStyleSignature, rawBodySignature] = await Promise.all([
        hmacHex(webhookSecret, timestampHeader + "." + canonicalPayload),
        hmacHex(webhookSecret, timestampHeader + "." + rawBody),
      ]);
      signatureIsValid = (
        constantTimeEqual(providedSignature, phpStyleSignature)
        || constantTimeEqual(providedSignature, rawBodySignature)
      );
    } catch {
      return jsonResponse(500, { error: "signature_verification_unavailable" });
    }
    if (!signatureIsValid) {
      return jsonResponse(401, { error: "invalid_webhook_signature" });
    }

    // GeniusPay's dashboard/API test event proves delivery and HMAC only.
    // It carries no payment transaction and must never mutate order state.
    if (payloadEvent === "webhook.test") {
      return jsonResponse(200, {
        received: true,
        test: true,
        signature_verified: true,
      });
    }

    // payment.initiated is subscribed in the merchant dashboard but does not
    // change persisted order/payment state. Acknowledge it after HMAC
    // verification so GeniusPay does not retry an event SHOPLINOUS does not use.
    if (payloadEvent === "payment.initiated") {
      return jsonResponse(200, { received: true, ignored: true, event: payloadEvent });
    }

    const data = payload.data;
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return jsonResponse(400, { error: "missing_payment_data" });
    }
    const payment = data as Record<string, unknown>;
    const metadata = payment.metadata;
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
      return jsonResponse(400, { error: "missing_order_metadata" });
    }
    const meta = metadata as Record<string, unknown>;

    const eventId = typeof payload.id === "string" ? payload.id.trim() : "";
    const reference = typeof payment.reference === "string" ? payment.reference.trim() : "";
    const orderNumber = typeof meta.order_id === "string" ? meta.order_id.trim() : "";
    const currency = typeof payment.currency === "string" ? payment.currency.toUpperCase() : "";
    const providerStatus = typeof payment.status === "string" ? payment.status.toLowerCase() : "";
    const amount = Number(payment.amount);

    if (
      !eventId ||
      !reference ||
      !orderNumber ||
      !Number.isFinite(amount) ||
      amount <= 0 ||
      !/^[A-Z]{3}$/.test(currency) ||
      !providerStatus
    ) {
      return jsonResponse(400, { error: "invalid_payment_fields" });
    }
    if (payloadEvent === "payment.success" && providerStatus !== "completed") {
      return jsonResponse(400, { error: "success_event_not_completed" });
    }

    let payloadHash = "";
    try {
      payloadHash = await sha256Hex(canonicalPayload);
    } catch {
      return jsonResponse(500, { error: "payload_hash_unavailable" });
    }

    try {
      const { data: result, error } = await dependencies.processEvent({
        p_event_id: eventId,
        p_delivery_id: deliveryHeader,
        p_reference: reference,
        p_event_type: payloadEvent,
        p_environment: payloadEnvironment,
        p_amount: amount,
        p_currency: currency,
        p_order_number: orderNumber,
        p_provider_status: providerStatus,
        p_payload_sha256: payloadHash,
      });

      if (error) {
        // Validation mismatches are permanent. Unknown references remain retryable
        // because GeniusPay may deliver the webhook before checkout finalization.
        const permanentCodes = new Set(["22023", "23505", "23514"]);
        if (error.code && permanentCodes.has(error.code)) {
          return jsonResponse(400, { error: "webhook_rejected_or_unmatched" });
        }
        return jsonResponse(503, { error: "webhook_persistence_unavailable" });
      }
      return jsonResponse(200, {
        received: true,
        duplicate: Boolean(result?.duplicate),
        payment_status: result?.payment_status ?? null,
        order_status: result?.order_status ?? null,
      });
    } catch {
      return jsonResponse(503, { error: "webhook_persistence_unavailable" });
    }
  };
}
