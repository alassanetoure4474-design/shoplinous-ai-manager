import { createClient } from "npm:@supabase/supabase-js@2";

const encoder = new TextEncoder();
const MAX_BODY_BYTES = 64 * 1024;
const WEBHOOK_WINDOW_SECONDS = 300;
const ALLOWED_EVENTS = new Set([
  "payment.success",
  "payment.failed",
  "payment.cancelled",
  "payment.expired",
  "payment.refunded",
]);

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

async function hmacHex(secret: string, message: string): Promise<string> {
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

function phpJsonEncode(value: unknown): string {
  // GeniusPay documents PHP json_encode($payload): compact JSON, escaped
  // forward slashes and escaped non-ASCII code units.
  const compact = JSON.stringify(value);
  return compact
    .replace(/\//g, "\\/")
    .replace(/[\u007f-\uffff]/g, (character) =>
      "\\u" + character.charCodeAt(0).toString(16).padStart(4, "0")
    );
}

async function sha256Hex(value: string): Promise<string> {
  return bytesToHex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

function getSupabaseSecretKey(): string {
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;

  // Supabase also exposes the newer named secret-key dictionary.
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

Deno.serve(async (request: Request): Promise<Response> => {
  if (request.method !== "POST") {
    return jsonResponse(405, { error: "method_not_allowed" });
  }

  const webhookSecret = Deno.env.get("GENIUSPAY_WEBHOOK_SECRET") ?? "";
  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const supabaseKey = getSupabaseSecretKey();
  if (!webhookSecret || !supabaseUrl || !supabaseKey) {
    return jsonResponse(503, { error: "webhook_not_configured" });
  }

  const signatureHeader = request.headers.get("X-Webhook-Signature") ?? "";
  const timestampHeader = request.headers.get("X-Webhook-Timestamp") ?? "";
  const eventHeader = request.headers.get("X-Webhook-Event") ?? "";
  const environmentHeader = request.headers.get("X-Webhook-Environment") ?? "";
  const deliveryHeader = request.headers.get("X-Webhook-Delivery");

  if (!signatureHeader || !timestampHeader || !eventHeader || !environmentHeader) {
    return jsonResponse(400, { error: "missing_webhook_headers" });
  }

  const timestamp = Number(timestampHeader);
  const now = Math.floor(Date.now() / 1000);
  if (!Number.isSafeInteger(timestamp) || Math.abs(now - timestamp) > WEBHOOK_WINDOW_SECONDS) {
    return jsonResponse(401, { error: "webhook_timestamp_invalid_or_expired" });
  }

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
  if (
    !payloadEvent ||
    !ALLOWED_EVENTS.has(payloadEvent) ||
    payloadEvent !== eventHeader ||
    !payloadEnvironment ||
    payloadEnvironment !== environmentHeader.toLowerCase() ||
    !Number.isSafeInteger(payloadTimestamp) ||
    payloadTimestamp !== timestamp
  ) {
    return jsonResponse(400, { error: "webhook_headers_payload_mismatch" });
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
    const supabase = createClient(supabaseUrl, supabaseKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data: result, error } = await supabase.rpc(
      "shoplinous_process_geniuspay_webhook",
      {
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
      },
    );

    if (error) {
      // Do not log provider payloads, signatures, secrets, or database details.
      return jsonResponse(409, { error: "webhook_rejected_or_unmatched" });
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
});
