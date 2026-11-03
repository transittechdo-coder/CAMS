// Shared helpers for the CAMS licence server.
import { createClient, SupabaseClient } from "npm:@supabase/supabase-js@2";

export const GRACE_DAYS = 10;        // full features after paid_until
export const FILE_VALID_DAYS = 14;   // offline time before CAMS must renew
export const TRIAL_DAYS = 14;
export const MAX_ACTIVATIONS_PER_YEAR = 4; // first install + 3 moves

export const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

export function db(): SupabaseClient {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );
}

// ---------- encoding helpers ----------
const enc = new TextEncoder();
export function b64(bytes: ArrayBuffer | Uint8Array): string {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = "";
  for (const b of u8) s += String.fromCharCode(b);
  return btoa(s);
}
export function unb64(s: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}
export async function sha256Hex(text: string): Promise<string> {
  const h = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------- licence keys ----------
const KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I
export function newLicenceKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const chars = [...bytes].map((b) => KEY_ALPHABET[b % KEY_ALPHABET.length]).join("");
  return `CAMS-${chars.slice(0, 4)}-${chars.slice(4, 8)}-${chars.slice(8, 12)}-${chars.slice(12, 16)}`;
}
export function normaliseKey(key: string): string {
  return String(key ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}
export async function hashKey(key: string): Promise<string> {
  return sha256Hex("cams-key:" + normaliseKey(key));
}
export async function hashFingerprint(fp: string): Promise<string> {
  return sha256Hex("cams-fp:" + String(fp ?? "").trim());
}

// ---------- Tanzanian phone numbers ----------
export function normalisePhone(raw: string): string | null {
  let p = String(raw ?? "").replace(/[^0-9]/g, "");
  if (p.startsWith("0") && p.length === 10) p = "255" + p.slice(1);
  if (p.length === 9) p = "255" + p;
  return /^255[67][0-9]{8}$/.test(p) ? p : null;
}
export function detectNetwork(phone255: string): string | null {
  const prefix = "0" + phone255.slice(3, 5);
  if (["074", "075", "076"].includes(prefix)) return "mpesa";
  if (["068", "069", "078"].includes(prefix)) return "airtel";
  if (["065", "067", "071", "077"].includes(prefix)) return "mixx";
  if (["061", "062"].includes(prefix)) return "halopesa";
  return null;
}

// ---------- signing ----------
let cachedKeys: { priv: CryptoKey; pubB64: string } | null = null;

export async function signingKeys(sb: SupabaseClient) {
  if (cachedKeys) return cachedKeys;
  let { data } = await sb.rpc("get_signing_key");
  let row = Array.isArray(data) ? data[0] : data;
  if (!row) {
    // First run: make the key pair on the server. The private key never leaves the database.
    const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
    const privB64 = b64(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
    const pubB64 = b64(await crypto.subtle.exportKey("raw", pair.publicKey));
    await sb.rpc("set_signing_key", { p_private: privB64, p_public: pubB64 });
    ({ data } = await sb.rpc("get_signing_key"));
    row = Array.isArray(data) ? data[0] : data;
  }
  const priv = await crypto.subtle.importKey("pkcs8", unb64(row.private_pkcs8_b64), { name: "Ed25519" }, false, ["sign"]);
  cachedKeys = { priv, pubB64: row.public_raw_b64 };
  return cachedKeys;
}

// ---------- licence file ----------
type Plan = {
  code: string; name: string; max_cameras: number | null; max_phones: number | null; features: string[];
};

export async function buildLicenceFile(sb: SupabaseClient, licenceId: string, fingerprintHash: string) {
  const { data: lic, error } = await sb
    .from("licences")
    .select("id, key_hint, plan_code, extra_cameras, status, trial_ends_at, paid_until, customer:customers(name)")
    .eq("id", licenceId)
    .single();
  if (error || !lic) throw new Error("licence not found");

  const { data: plans } = await sb.from("plans").select("code, name, max_cameras, max_phones, features");
  const byCode = Object.fromEntries((plans ?? []).map((p: Plan) => [p.code, p])) as Record<string, Plan>;

  const now = new Date();
  const paidUntil = lic.paid_until ? new Date(lic.paid_until) : null;
  const trialEnds = lic.trial_ends_at ? new Date(lic.trial_ends_at) : null;
  const graceUntil = paidUntil ? new Date(paidUntil.getTime() + GRACE_DAYS * 864e5) : null;

  // Which plan's features are unlocked right now
  let state: string;
  let planCode: string;
  if (lic.status === "trial" && trialEnds && trialEnds > now) {
    state = "trial"; planCode = "premium";
  } else if (paidUntil && paidUntil > now) {
    state = paidUntil.getTime() - now.getTime() <= 7 * 864e5 ? "due_soon" : "active";
    planCode = lic.plan_code;
  } else if (graceUntil && graceUntil > now) {
    state = "grace"; planCode = lic.plan_code;
  } else if (paidUntil) {
    state = "limited"; planCode = "free"; // recording + live view + emergency alerts always stay on
  } else {
    state = "free"; planCode = "free";
  }

  const plan = byCode[planCode];
  const paidPlan = byCode[lic.plan_code];
  const maxCameras = plan.max_cameras === null ? null : plan.max_cameras + (planCode === lic.plan_code ? lic.extra_cameras : 0);

  const payload = {
    v: 1,
    licence_id: lic.id,
    key_hint: lic.key_hint,
    customer: (lic as any).customer?.name ?? null,
    state,
    plan: plan.code,
    plan_name: plan.name,
    paid_plan: paidPlan.code,
    max_cameras: maxCameras,
    max_phones: plan.max_phones,
    features: plan.features,
    // CAMS rule: these never switch off because of payment
    always_on: ["live_view", "recording", "emergency_alerts"],
    device: fingerprintHash,
    trial_ends_at: trialEnds?.toISOString() ?? null,
    paid_until: paidUntil?.toISOString() ?? null,
    grace_until: graceUntil?.toISOString() ?? null,
    issued_at: now.toISOString(),
    valid_until: new Date(now.getTime() + FILE_VALID_DAYS * 864e5).toISOString(),
    renew_after: new Date(now.getTime() + 7 * 864e5).toISOString(),
  };

  const { priv, pubB64 } = await signingKeys(sb);
  const data = b64(enc.encode(JSON.stringify(payload)));
  const sig = b64(await crypto.subtle.sign({ name: "Ed25519" }, priv, enc.encode(data)));
  return { licence_file: { alg: "Ed25519", data, sig }, licence: payload, public_key: pubB64 };
}

export async function logEvent(sb: SupabaseClient, licenceId: string, event: string, details: unknown = {}) {
  await sb.from("licence_events").insert({ licence_id: licenceId, event, details });
}

export function priceFor(plan: { monthly_price_tzs: number; yearly_price_tzs: number | null; extra_camera_price_tzs: number | null }, months: number, extraCameras: number) {
  const base = months === 12 ? (plan.yearly_price_tzs ?? plan.monthly_price_tzs * 12) : plan.monthly_price_tzs;
  return base + extraCameras * (plan.extra_camera_price_tzs ?? 0) * months;
}
