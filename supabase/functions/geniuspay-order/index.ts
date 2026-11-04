// Edge Function publique : point d'entree du paiement GeniusPay.
// - Mode reel (fw_order) : lit la commande Freewebstore cote serveur
//   (x-api-key), verifie l'e-mail du client, calcule le montant, cree le
//   checkout heberge GeniusPay, renvoie l'URL de paiement.
// - Mode test (prefixe TEST-) : autorise uniquement si le secret Supabase
//   GENIUSPAY_TEST_MODE=true (demonstration sandbox sans commande FW).
// Aucun secret n'est expose ; aucune donnee personnelle n'est stockee.

const GENIUSPAY_API_BASE =
  (Deno.env.get("GENIUSPAY_API_BASE") || "https://geniuspay.ci/api/v1/merchant");
const FW_API_BASE =
  (Deno.env.get("FREEWEBSTORE_API_BASE") || "https://api.freewebstore.com").replace(/\/$/, "");

const CORS_HEADERS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, "content-type": "application/json" },
  });
}

function sha256Hex(value: string): Promise<string> {
  const data = new TextEncoder().encode(value);
  return crypto.subtle.digest("SHA-256", data).then((buf) => {
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0")).join("");
  });
}

interface SupabaseCredentials {
  url: string;
  key: string;
  authHeader: "apikey" | "bearer";
}

function getSupabaseCredentials(): SupabaseCredentials | null {
  const url = Deno.env.get("SUPABASE_URL");
  if (!url) return null;
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy && !legacy.startsWith("sb_secret_")) {
    return { url, key: legacy, authHeader: "bearer" };
  }
  const secret = Deno.env.get("SUPABASE_SECRET_KEY") ||
    (Deno.env.get("SUPABASE_SECRET_KEYS")
      ? JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS")!).default
      : null);
  if (secret) {
    return { url, key: secret, authHeader: "apikey" };
  }
  return legacy ? { url, key: legacy, authHeader: "apikey" } : null;
}

async function callSupabaseRpc(
  creds: SupabaseCredentials,
  fn: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    apikey: creds.key,
  };
  if (creds.authHeader === "bearer") {
    headers.authorization = "Bearer " + creds.key;
  }
  const resp = await fetch(
    creds.url + "/rest/v1/rpc/" + fn,
    {
      method: "POST",
      headers,
      body: JSON.stringify(args),
    },
  );
  const text = await resp.text();
  let parsed: unknown = null;
  try { parsed = text ? JSON.parse(text) : null; } catch (_) { /* vide */ }
  if (!resp.ok) {
    const message = (parsed && typeof parsed === "object" &&
      "message" in parsed && typeof (parsed as Record<string, unknown>).message === "string")
      ? (parsed as Record<string, string>).message
      : text.slice(0, 300);
    throw new SupabaseRpcError(resp.status, message);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new SupabaseRpcError(500, "Reponse RPC invalide");
  }
  return parsed as Record<string, unknown>;
}

class SupabaseRpcError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface FwOrder {
  id: string;
  currency?: string;
  total?: number;
  postage?: number;
  order_details?: Array<{ net?: number; total?: number }>;
  delivery_address?: { country_iso_2?: string };
  billing_address?: { email?: string; country_iso_2?: string };
  email?: string;
  customer?: { email?: string };
}

async function fetchFwOrder(
  apiKey: string,
  orderId: string,
): Promise<FwOrder | "not_found" | "error"> {
  const headers = { "x-api-key": apiKey, accept: "application/json" };
  const direct = await fetch(
    FW_API_BASE + "/order/" + encodeURIComponent(orderId),
    { headers },
  );
  if (direct.ok) {
    const order = await direct.json();
    if (order && typeof order === "object") return order as FwOrder;
  }
  if (direct.status === 401 || direct.status === 403) return "error";
  // Repli : parcours de la liste des commandes.
  const list = await fetch(
    FW_API_BASE + "/orders?limit=100&offset=0",
    { headers },
  );
  if (!list.ok) return "error";
  const data = await list.json();
  const orders = Array.isArray(data) ? data
    : (data && typeof data === "object" && Array.isArray(
        (data as Record<string, unknown>).orders)
      ? (data as Record<string, unknown>).orders
      : (data && typeof data === "object" && Array.isArray(
          (data as Record<string, unknown>).items)
        ? (data as Record<string, unknown>).items
        : null));
  if (!orders) return "error";
  for (const o of orders as FwOrder[]) {
    if (o && typeof o.id !== "undefined" && String(o.id) === orderId) {
      return o;
    }
  }
  return "not_found";
}

function extractFwEmail(order: FwOrder): string | null {
  const candidates = [
    order.email,
    order.billing_address?.email,
    order.customer?.email,
  ];
  for (const c of candidates) {
    if (typeof c === "string" && c.includes("@")) {
      return c.trim().toLowerCase();
    }
  }
  return null;
}

function computeFwTotal(order: FwOrder): number | null {
  if (typeof order.total === "number" && order.total > 0) {
    return order.total;
  }
  const details = Array.isArray(order.order_details) ? order.order_details : [];
  let sum = 0;
  for (const d of details) {
    const line = typeof d.total === "number" ? d.total : d.net;
    if (typeof line === "number" && line > 0) sum += line;
  }
  const postage = typeof order.postage === "number" ? order.postage : 0;
  if (sum + postage > 0) {
    return Math.round((sum + postage) * 100) / 100;
  }
  return null;
}

function apiUnitsFromOrder(amount: number, currency: string): number {
  if (currency === "EUR") return Math.round(amount * 100);
  return Math.round(amount);
}

function isAllowedCheckoutHost(url: string): boolean {
  let parsed: URL;
  try { parsed = new URL(url); } catch (_) { return false; }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  return host === "geniuspay.ci" ||
    host.endsWith(".geniuspay.ci") ||
    host === "wave.com" ||
    host.endsWith(".wave.com");
}

async function handleStatus(orderNumber: string): Promise<Response> {
  const creds = getSupabaseCredentials();
  if (!creds) {
    return json({ error: "supabase_credentials_unavailable" }, 503);
  }
  try {
    const status = await callSupabaseRpc(creds, "shoplinous_order_status", {
      p_order_number: orderNumber,
    });
    return json({ order_number: orderNumber, ...status });
  } catch (err) {
    if (err instanceof SupabaseRpcError && err.status === 404) {
      return json({ error: "order_not_found" }, 404);
    }
    return json({
      error: "status_unavailable",
      detail: err instanceof SupabaseRpcError ? err.message.slice(0, 160) : "",
    }, 503);
  }
}

async function createGeniuspayCheckout(
  apiKey: string,
  apiSecret: string,
  orderNumber: string,
  amountApi: number,
  currency: string,
  method: string,
  country: string,
): Promise<{ reference: string; checkout_url: string }> {
  const body: Record<string, unknown> = {
    amount: amountApi,
    currency,
    description: "Commande " + orderNumber + " - Shoplinous",
    metadata: { order_id: orderNumber },
  };
  if (method === "wave") {
    body.payment_method = "wave";
    body.gateway = "wave";
    body.customer = { country: "CI" };
  }
  const resp = await fetch(GENIUSPAY_API_BASE + "/payments", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "accept": "application/json",
      "x-api-key": apiKey,
      "x-api-secret": apiSecret,
    },
    body: JSON.stringify(body),
  });
  const text = await resp.text();
  let parsed: Record<string, unknown> | null = null;
  try { parsed = text ? JSON.parse(text) : null; } catch (_) { parsed = null; }
  if (!resp.ok || !parsed || parsed.success !== true) {
    const detail = parsed && typeof parsed.message === "string"
      ? parsed.message
      : ("HTTP " + resp.status + " " + text.slice(0, 150));
    throw new GeniuspayError("geniuspay_checkout_refused", detail.slice(0, 200));
  }
  const data = (parsed.data ?? {}) as Record<string, unknown>;
  const reference = typeof data.reference === "string" ? data.reference : null;
  const checkoutUrl = typeof data.checkout_url === "string"
    ? data.checkout_url
    : null;
  const status = typeof data.status === "string" ? data.status : null;
  const environment = typeof data.environment === "string"
    ? data.environment
    : null;
  if (!reference || !checkoutUrl || !isAllowedCheckoutHost(checkoutUrl)) {
    throw new GeniuspayError("geniuspay_invalid_checkout_response", "");
  }
  if (status && !["none", "pending", "processing"].includes(status)) {
    throw new GeniuspayError("geniuspay_unexpected_checkout_status", status);
  }
  if (environment && environment !== "sandbox") {
    throw new GeniuspayError("geniuspay_unexpected_environment", environment);
  }
  if (method === "wave") {
    const gateway = typeof data.gateway === "string" ? data.gateway : null;
    if (gateway && gateway !== "wave") {
      throw new GeniuspayError("geniuspay_wave_gateway_mismatch", gateway);
    }
    const echoAmount = typeof data.amount === "number" ? data.amount : null;
    if (echoAmount !== null && echoAmount !== amountApi) {
      throw new GeniuspayError("geniuspay_amount_mismatch", String(echoAmount));
    }
  }
  return { reference, checkout_url: checkoutUrl };
}

class GeniuspayError extends Error {
  code: string;
  detail: string;
  constructor(code: string, detail: string) {
    super(code);
    this.code = code;
    this.detail = detail;
  }
}

interface StartRequest {
  orderNumber: string;
  email: string;
  amount?: number;
  currency?: string;
  country?: string;
  redirect?: boolean;
}

function parseStartRequest(url: URL, bodyJson: unknown): StartRequest | null {
  const src: Record<string, unknown> =
    (bodyJson && typeof bodyJson === "object")
      ? bodyJson as Record<string, unknown>
      : Object.fromEntries(url.searchParams.entries());
  const orderNumber = typeof src.order_number === "string"
    ? src.order_number.trim()
    : (typeof src.orderNumber === "string" ? src.orderNumber.trim() : "");
  const email = typeof src.email === "string"
    ? src.email.trim().toLowerCase()
    : "";
  if (!orderNumber || orderNumber.length > 120) return null;
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return null;
  const amount = typeof src.amount === "number" ? src.amount : undefined;
  const currency = typeof src.currency === "string"
    ? src.currency.toUpperCase()
    : undefined;
  const country = typeof src.country === "string"
    ? src.country.toUpperCase()
    : undefined;
  const redirect = src.redirect === "1" || src.redirect === true;
  return { orderNumber, email, amount, currency, country, redirect };
}

async function handleStart(req: StartRequest): Promise<Response> {
  const testMode = Deno.env.get("GENIUSPAY_TEST_MODE") === "true";
  const isTestOrder = req.orderNumber.startsWith("TEST-");
  if (isTestOrder && !testMode) {
    return json({ error: "test_mode_disabled" }, 403);
  }

  let currency: string;
  let method: string;
  let country: string;
  let amountMajor: number;

  if (isTestOrder) {
    currency = (req.currency || "EUR").toUpperCase();
    amountMajor = typeof req.amount === "number" ? req.amount : NaN;
    if (currency === "EUR") {
      method = "card";
      country = (req.country || "FR").toUpperCase();
      if (!(amountMajor >= 2 && amountMajor <= 1000000) ||
          Math.abs(Math.round(amountMajor * 100) - amountMajor * 100) >= 1e-6) {
        return json({ error: "invalid_test_amount" }, 400);
      }
    } else if (currency === "XOF") {
      method = "wave";
      country = "CI";
      if (!(amountMajor >= 200 && Number.isInteger(amountMajor))) {
        return json({ error: "invalid_test_amount" }, 400);
      }
    } else {
      return json({ error: "unsupported_currency" }, 400);
    }
  } else {
    const fwKey = Deno.env.get("FREEWEBSTORE_API_KEY");
    if (!fwKey) {
      return json({ error: "freewebstore_not_configured" }, 503);
    }
    const order = await fetchFwOrder(fwKey, req.orderNumber);
    if (order === "error") {
      return json({ error: "freewebstore_api_unavailable" }, 502);
    }
    if (order === "not_found") {
      return json({ error: "order_not_found" }, 404);
    }
    const orderEmail = extractFwEmail(order);
    if (!orderEmail || orderEmail !== req.email) {
      return json({ error: "order_email_mismatch" }, 403);
    }
    const total = computeFwTotal(order);
    if (total === null || !(total > 0)) {
      return json({ error: "order_amount_unavailable" }, 422);
    }
    currency = (order.currency || "EUR").toUpperCase();
    if (currency === "EUR") {
      method = "card";
      const c = order.delivery_address?.country_iso_2 ||
        order.billing_address?.country_iso_2 || "FR";
      country = c.toUpperCase();
    } else if (currency === "XOF") {
      method = "wave";
      const c = order.delivery_address?.country_iso_2 ||
        order.billing_address?.country_iso_2 || "";
      country = c.toUpperCase();
      if (country !== "CI") {
        return json({ error: "wave_requires_ci" }, 422);
      }
    } else {
      return json({ error: "unsupported_currency" }, 422);
    }
    amountMajor = total;
  }

  const creds = getSupabaseCredentials();
  if (!creds) {
    return json({ error: "supabase_credentials_unavailable" }, 503);
  }
  const apiKey = Deno.env.get("GENIUSPAY_API_KEY");
  const apiSecret = Deno.env.get("GENIUSPAY_API_SECRET");
  if (!apiKey || !apiSecret) {
    return json({ error: "geniuspay_credentials_unavailable" }, 503);
  }

  // Nombre de tentatives precedentes => cle d'idempotence par tentative.
  let attempts = 1;
  let reusedCheckoutUrl: string | null = null;
  try {
    const status = await callSupabaseRpc(creds, "shoplinous_order_status", {
      p_order_number: req.orderNumber,
    });
    attempts = typeof status.attempts === "number" ? status.attempts + 1 : 1;
    const payStatus = typeof status.payment_status === "string"
      ? status.payment_status
      : null;
    if (payStatus === "pending" && typeof status.checkout_url === "string") {
      reusedCheckoutUrl = status.checkout_url;
    }
  } catch (_) {
    // Commande inconnue : premiere tentative.
  }

  const idemBase = await sha256Hex(
    req.orderNumber + "|" + method + "|" + "sandbox",
  );
  const idempotencyKey = "ord-" + idemBase.slice(0, 32) + "-" + attempts;

  let reserve: Record<string, unknown>;
  try {
    reserve = await callSupabaseRpc(creds, "shoplinous_reserve_payment", {
      p_order_number: req.orderNumber,
      p_country: country,
      p_currency: currency,
      p_order_amount: amountMajor,
      p_method: method,
      p_idempotency_key: idempotencyKey,
      p_environment: "sandbox",
    });
  } catch (err) {
    if (err instanceof SupabaseRpcError) {
      if (err.status === 409 || /already_reserved/.test(err.message)) {
        return json({
          error: "payment_already_reserved",
          order_number: req.orderNumber,
        }, 409);
      }
      return json({
        error: "reservation_failed",
        detail: err.message.slice(0, 160),
      }, 409);
    }
    return json({ error: "reservation_failed" }, 503);
  }

  const paymentId = typeof reserve.payment_id === "string"
    ? reserve.payment_id
    : null;
  const existingUrl = typeof reserve.checkout_url === "string"
    ? reserve.checkout_url
    : null;
  if (!paymentId) {
    return json({ error: "reservation_failed" }, 503);
  }
  if (existingUrl && isAllowedCheckoutHost(existingUrl)) {
    const ref = typeof reserve.provider_reference === "string"
      ? reserve.provider_reference
      : null;
    return finish(req, existingUrl, ref);
  }
  if (reusedCheckoutUrl && isAllowedCheckoutHost(reusedCheckoutUrl)) {
    return finish(req, reusedCheckoutUrl, null);
  }

  const amountApi = apiUnitsFromOrder(amountMajor, currency);
  let checkout: { reference: string; checkout_url: string };
  let simulated = false;
  try {
    checkout = await createGeniuspayCheckout(
      apiKey,
      apiSecret,
      req.orderNumber,
      amountApi,
      currency,
      method,
      country,
    );
  } catch (err) {
    if (err instanceof GeniuspayError) {
      // En mode TEST uniquement : si GeniusPay refuse la creation de
      // paiement parce que le quota sandbox marchand est epuise
      // ("No tokens remaining"), on simule une reference pour valider le
      // reste de la chaine (finalisation, webhook HMAC, rapprochement).
      // La reponse porte "simulated": true : ce n'est JAMAIS une preuve
      // de checkout reel GeniusPay.
      if (isTestOrder && err.code === "geniuspay_checkout_refused" &&
          /No tokens remaining/i.test(err.detail) &&
          Deno.env.get("GENIUSPAY_TEST_MODE") === "true") {
        simulated = true;
        const simRef = "TESTREF-" +
          crypto.randomUUID().replace(/-/g, "").slice(0, 12).toUpperCase();
        checkout = {
          reference: simRef,
          checkout_url: "https://geniuspay.ci/checkout/" + simRef,
        };
      } else {
        return json({
          error: err.code,
          detail: err.detail.slice(0, 120),
          order_number: req.orderNumber,
        }, 502);
      }
    } else {
      return json({ error: "geniuspay_api_unavailable" }, 502);
    }
  }

  try {
    await callSupabaseRpc(creds, "shoplinous_finalize_checkout", {
      p_payment_id: paymentId,
      p_reference: checkout.reference,
      p_checkout_url: checkout.checkout_url,
      p_environment: "sandbox",
    });
  } catch (_) {
    return json({ error: "checkout_finalization_failed" }, 503);
  }

  if (simulated) {
    return json({
      order_number: req.orderNumber,
      checkout_url: checkout.checkout_url,
      reference: checkout.reference,
      status: "pending",
      environment: "sandbox",
      simulated: true,
      notice: "Checkout simule : quota sandbox GeniusPay epuise (creation reelle refusee). A revalider apres recharge du quota.",
    });
  }
  return finish(req, checkout.checkout_url, checkout.reference);
}

function finish(
  req: StartRequest,
  checkoutUrl: string,
  reference: string | null,
): Response {
  if (req.redirect) {
    return new Response(null, {
      status: 303,
      headers: { ...CORS_HEADERS, location: checkoutUrl },
    });
  }
  const body: Record<string, unknown> = {
    order_number: req.orderNumber,
    checkout_url: checkoutUrl,
    status: "pending",
    environment: "sandbox",
  };
  if (reference) {
    body.reference = reference;
  }
  return json(body);
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  const url = new URL(request.url);
  const action = url.searchParams.get("action");
  if (request.method === "GET" && action === "status") {
    const orderNumber = url.searchParams.get("order_number");
    if (!orderNumber) {
      return json({ error: "missing_order_number" }, 400);
    }
    return handleStatus(orderNumber.trim());
  }
  if (request.method === "GET") {
    const parsed = parseStartRequest(url, null);
    if (!parsed) {
      return json({ error: "invalid_request" }, 400);
    }
    return handleStart(parsed);
  }
  if (request.method === "POST") {
    let body: unknown = null;
    try {
      body = await request.json();
    } catch (_) {
      return json({ error: "invalid_json_body" }, 400);
    }
    const parsed = parseStartRequest(url, body);
    if (!parsed) {
      return json({ error: "invalid_request" }, 400);
    }
    return handleStart(parsed);
  }
  return json({ error: "method_not_allowed" }, 405);
});
