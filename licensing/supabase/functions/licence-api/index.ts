// CAMS licence API — called by the CAMS desktop app.
// Actions: public_key, plans, start_trial, activate, renew, deactivate, start_payment, payment_status
import {
  buildLicenceFile, cors, db, detectNetwork, hashFingerprint, hashKey, json, logEvent,
  MAX_ACTIVATIONS_PER_YEAR, newLicenceKey, normaliseKey, normalisePhone, priceFor, signingKeys, TRIAL_DAYS,
} from "./licence.ts";

const PAYMENT_GATEWAY = Deno.env.get("PAYMENT_GATEWAY") ?? "sandbox";
const PAYMENT_TIMEOUT_MIN = 10;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);

  let body: Record<string, any>;
  try { body = await req.json(); } catch { return json({ error: "Invalid JSON" }, 400); }

  const sb = db();
  const action = String(body.action ?? "");

  try {
    switch (action) {
      // ---------- public info ----------
      case "public_key": {
        const { pubB64 } = await signingKeys(sb);
        return json({ alg: "Ed25519", public_key: pubB64 });
      }
      case "plans": {
        const { data } = await sb.from("plans")
          .select("code, name, monthly_price_tzs, yearly_price_tzs, max_cameras, max_phones, extra_camera_price_tzs, features")
          .order("sort_order");
        return json({ plans: data });
      }

      // ---------- free trial (needs internet once) ----------
      case "start_trial": {
        if (!body.fingerprint) return json({ error: "fingerprint is required" }, 400);
        const fp = await hashFingerprint(body.fingerprint);

        // One trial per computer
        const { data: used } = await sb.from("devices").select("id").eq("fingerprint_hash", fp).limit(1);
        if (used && used.length) {
          return json({ error: "trial_used", message: "This computer has already used its free trial." }, 409);
        }

        const key = newLicenceKey();
        const { data: lic, error } = await sb.from("licences").insert({
          key_hash: await hashKey(key),
          key_hint: key.slice(-4),
          plan_code: "premium",
          status: "trial",
          trial_ends_at: new Date(Date.now() + TRIAL_DAYS * 864e5).toISOString(),
        }).select("id").single();
        if (error) throw error;

        await sb.from("devices").insert({
          licence_id: lic.id, fingerprint_hash: fp,
          computer_name: body.computer_name ?? null, cams_version: body.cams_version ?? null,
          last_seen_at: new Date().toISOString(),
        });
        await logEvent(sb, lic.id, "trial_started", { computer_name: body.computer_name ?? null });
        return json({ licence_key: key, ...(await buildLicenceFile(sb, lic.id, fp)) });
      }

      // ---------- activate a bought key ----------
      case "activate": {
        if (!body.licence_key || !body.fingerprint) return json({ error: "licence_key and fingerprint are required" }, 400);
        const fp = await hashFingerprint(body.fingerprint);

        // Rate limit: 10 failed tries per hour per computer
        const since = new Date(Date.now() - 3600e3).toISOString();
        const { count } = await sb.from("activation_attempts").select("id", { count: "exact", head: true })
          .eq("fingerprint_hash", fp).eq("ok", false).gte("created_at", since);
        if ((count ?? 0) >= 10) return json({ error: "too_many_tries", message: "Too many wrong keys. Try again in one hour." }, 429);

        if (normaliseKey(body.licence_key).length !== 20) {
          await sb.from("activation_attempts").insert({ fingerprint_hash: fp, ok: false });
          return json({ error: "key_not_found", message: "Key not found. Check the key and try again." }, 404);
        }

        const { data: lic } = await sb.from("licences").select("id, status")
          .eq("key_hash", await hashKey(body.licence_key)).maybeSingle();
        await sb.from("activation_attempts").insert({ fingerprint_hash: fp, ok: !!lic });
        if (!lic) return json({ error: "key_not_found", message: "Key not found. Check the key and try again." }, 404);
        if (lic.status === "revoked") return json({ error: "revoked", message: "This key has been cancelled. Contact Transit Tech." }, 403);

        const { data: active } = await sb.from("devices").select("id, fingerprint_hash")
          .eq("licence_id", lic.id).eq("active", true).maybeSingle();

        if (active && active.fingerprint_hash !== fp) {
          return json({ error: "key_in_use", message: "Key already used on another computer. Deactivate it there, or contact Transit Tech." }, 409);
        }

        if (!active) {
          const yearAgo = new Date(Date.now() - 365 * 864e5).toISOString();
          const { count: acts } = await sb.from("licence_events").select("id", { count: "exact", head: true })
            .eq("licence_id", lic.id).eq("event", "activated").gte("created_at", yearAgo);
          if ((acts ?? 0) >= MAX_ACTIVATIONS_PER_YEAR) {
            return json({ error: "too_many_moves", message: "This key has moved computers too many times this year. Contact Transit Tech." }, 403);
          }
          await sb.from("devices").insert({
            licence_id: lic.id, fingerprint_hash: fp,
            computer_name: body.computer_name ?? null, cams_version: body.cams_version ?? null,
            last_seen_at: new Date().toISOString(),
          });
          await logEvent(sb, lic.id, "activated", { computer_name: body.computer_name ?? null });
        } else {
          await sb.from("devices").update({ last_seen_at: new Date().toISOString(), cams_version: body.cams_version ?? null }).eq("id", active.id);
        }
        return json(await buildLicenceFile(sb, lic.id, fp));
      }

      // ---------- weekly renewal ----------
      case "renew": {
        const found = await findDevice(sb, body);
        if ("error" in found) return found.error as Response;
        await sb.from("devices").update({ last_seen_at: new Date().toISOString(), cams_version: body.cams_version ?? null })
          .eq("id", found.device.id);
        return json(await buildLicenceFile(sb, found.licence.id, found.fp));
      }

      // ---------- move to another computer ----------
      case "deactivate": {
        const found = await findDevice(sb, body);
        if ("error" in found) return found.error as Response;
        await sb.from("devices").update({ active: false }).eq("id", found.device.id);
        await logEvent(sb, found.licence.id, "deactivated", {});
        return json({ ok: true, message: "This computer is no longer using the key. You can now activate it on another computer." });
      }

      // ---------- pay with mobile money ----------
      case "start_payment": {
        const found = await findDevice(sb, body);
        if ("error" in found) return found.error as Response;

        const planCode = String(body.plan_code ?? "");
        const months = Number(body.months ?? 1);
        if (!["pro", "premium"].includes(planCode)) return json({ error: "Choose the Pro or Premium plan. Enterprise is set up by Transit Tech." }, 400);
        if (![1, 12].includes(months)) return json({ error: "months must be 1 or 12" }, 400);

        const phone = normalisePhone(body.phone);
        if (!phone) return json({ error: "bad_phone", message: "Enter a valid Tanzanian phone number, like 0754 123 456." }, 400);
        const network = detectNetwork(phone);
        if (!network) return json({ error: "bad_network", message: "Use an M-Pesa, Airtel Money, Mixx or HaloPesa number." }, 400);

        const { data: plan } = await sb.from("plans").select("*").eq("code", planCode).single();
        const { data: lic } = await sb.from("licences").select("extra_cameras").eq("id", found.licence.id).single();
        const amount = priceFor(plan, months, lic?.extra_cameras ?? 0);

        const { data: pay, error } = await sb.from("payments").insert({
          licence_id: found.licence.id, plan_code: planCode, amount_tzs: amount, months,
          phone, network, gateway: PAYMENT_GATEWAY,
        }).select("id").single();
        if (error) throw error;

        const sent = await sendUssdPush(pay.id, phone, amount);
        if (sent.gateway_ref) await sb.from("payments").update({ gateway_ref: sent.gateway_ref }).eq("id", pay.id);
        await logEvent(sb, found.licence.id, "payment_started", { payment_id: pay.id, amount_tzs: amount, months, plan_code: planCode });

        return json({
          payment_id: pay.id, amount_tzs: amount, network, phone,
          message: "Check your phone and enter your PIN to pay.",
          sandbox: PAYMENT_GATEWAY === "sandbox",
        });
      }

      case "payment_status": {
        const found = await findDevice(sb, body);
        if ("error" in found) return found.error as Response;
        const { data: pay } = await sb.from("payments").select("id, status, created_at, amount_tzs")
          .eq("id", body.payment_id).eq("licence_id", found.licence.id).maybeSingle();
        if (!pay) return json({ error: "payment_not_found" }, 404);

        let status = pay.status;
        if (status === "pending" && Date.now() - Date.parse(pay.created_at) > PAYMENT_TIMEOUT_MIN * 60e3) {
          await sb.from("payments").update({ status: "failed" }).eq("id", pay.id).eq("status", "pending");
          status = "failed";
        }
        if (status === "paid") {
          const { data: rc } = await sb.from("receipts").select("receipt_no").eq("payment_id", pay.id).maybeSingle();
          return json({ status, receipt_no: rc?.receipt_no ?? null, ...(await buildLicenceFile(sb, found.licence.id, found.fp)) });
        }
        return json({ status });
      }

      default:
        return json({ error: "Unknown action" }, 400);
    }
  } catch (e) {
    console.error(action, e);
    return json({ error: "server_error", message: "Something went wrong. Please try again." }, 500);
  }
});

// Finds the licence + this computer's active device from licence_key + fingerprint.
async function findDevice(sb: ReturnType<typeof db>, body: Record<string, any>) {
  if (!body.licence_key || !body.fingerprint) return { error: json({ error: "licence_key and fingerprint are required" }, 400) };
  const fp = await hashFingerprint(body.fingerprint);
  const { data: licence } = await sb.from("licences").select("id, status").eq("key_hash", await hashKey(body.licence_key)).maybeSingle();
  if (!licence) return { error: json({ error: "key_not_found" }, 404) };
  if (licence.status === "revoked") return { error: json({ error: "revoked", message: "This key has been cancelled. Contact Transit Tech." }, 403) };
  const { data: device } = await sb.from("devices").select("id").eq("licence_id", licence.id)
    .eq("fingerprint_hash", fp).eq("active", true).maybeSingle();
  if (!device) return { error: json({ error: "not_activated_here", message: "This key is not active on this computer. Activate it first." }, 403) };
  return { licence, device, fp };
}

// Payment gateway adapter. "sandbox" sends nothing; Transit Tech confirms test payments in the admin API.
// When a real gateway (ZenoPay, Selcom, AzamPay, ClickPesa...) is chosen, add its USSD-push call here.
async function sendUssdPush(paymentId: string, phone: string, amount: number): Promise<{ gateway_ref: string | null }> {
  if (PAYMENT_GATEWAY === "sandbox") return { gateway_ref: "SBX-" + paymentId.slice(0, 8) };
  throw new Error(`Payment gateway "${PAYMENT_GATEWAY}" is not connected yet (phone ${phone}, amount ${amount})`);
}
