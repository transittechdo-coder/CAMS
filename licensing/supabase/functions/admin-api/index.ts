// CAMS admin API — for Transit Tech staff only (signed-in Supabase user listed in public.admins).
// Actions: dashboard, list_licences, licence_detail, create_licence, record_payment,
//          confirm_sandbox_payment, change_plan, revoke, reset_device
import { createClient } from "npm:@supabase/supabase-js@2";
import { cors, db, hashKey, json, logEvent, newLicenceKey, normalisePhone, priceFor } from "./licence.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);

  // Who is calling?
  const authHeader = req.headers.get("Authorization") ?? "";
  const userClient = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: authHeader } }, auth: { persistSession: false },
  });
  const { data: { user } } = await userClient.auth.getUser();
  if (!user) return json({ error: "Sign in first" }, 401);

  const sb = db();
  const { data: admin } = await sb.from("admins").select("user_id").eq("user_id", user.id).maybeSingle();
  if (!admin) return json({ error: "Not an admin" }, 403);

  let body: Record<string, any>;
  try { body = await req.json(); } catch { return json({ error: "Invalid JSON" }, 400); }

  try {
    switch (body.action) {
      case "dashboard": {
        const monthStart = new Date(); monthStart.setUTCDate(1); monthStart.setUTCHours(0, 0, 0, 0);
        const now = new Date();
        const in7 = new Date(Date.now() + 7 * 864e5).toISOString();
        const graceStart = new Date(Date.now() - 10 * 864e5).toISOString();
        const [{ data: paid }, { count: active }, { count: grace }, { count: trials }] = await Promise.all([
          sb.from("payments").select("amount_tzs").eq("status", "paid").gte("paid_at", monthStart.toISOString()),
          sb.from("licences").select("id", { count: "exact", head: true }).gt("paid_until", now.toISOString()),
          sb.from("licences").select("id", { count: "exact", head: true }).lte("paid_until", now.toISOString()).gt("paid_until", graceStart),
          sb.from("licences").select("id", { count: "exact", head: true }).eq("status", "trial").gt("trial_ends_at", now.toISOString()).lte("trial_ends_at", in7),
        ]);
        return json({
          received_this_month_tzs: (paid ?? []).reduce((s, p) => s + p.amount_tzs, 0),
          active_licences: active ?? 0, in_grace: grace ?? 0, trials_ending_this_week: trials ?? 0,
        });
      }

      case "list_licences": {
        let q = sb.from("licences")
          .select("id, key_hint, plan_code, status, paid_until, trial_ends_at, extra_cameras, created_at, customer:customers(name, phone)")
          .order("created_at", { ascending: false }).limit(200);
        if (body.status) q = q.eq("status", body.status);
        const { data } = await q;
        const term = String(body.search ?? "").toLowerCase();
        const rows = term
          ? (data ?? []).filter((l: any) => `${l.customer?.name ?? ""} ${l.customer?.phone ?? ""} ${l.key_hint}`.toLowerCase().includes(term))
          : data;
        return json({ licences: rows });
      }

      case "licence_detail": {
        const id = body.licence_id;
        const [{ data: licence }, { data: devices }, { data: payments }, { data: events }] = await Promise.all([
          sb.from("licences").select("*, customer:customers(*)").eq("id", id).single(),
          sb.from("devices").select("computer_name, cams_version, activated_at, last_seen_at, active").eq("licence_id", id).order("activated_at", { ascending: false }),
          sb.from("payments").select("id, amount_tzs, months, plan_code, phone, network, gateway, gateway_ref, status, created_at, paid_at, receipt:receipts(receipt_no)").eq("licence_id", id).order("created_at", { ascending: false }),
          sb.from("licence_events").select("event, details, created_at").eq("licence_id", id).order("created_at", { ascending: false }).limit(50),
        ]);
        return json({ licence, devices, payments, events });
      }

      // New customer + key (e.g. after a site visit). Optionally records an upfront cash/bank payment.
      case "create_licence": {
        const c = body.customer ?? {};
        const phone = normalisePhone(c.phone);
        if (!c.name || !phone) return json({ error: "customer.name and a valid customer.phone are required" }, 400);
        const planCode = body.plan_code ?? "pro";

        const { data: cust, error: ce } = await sb.from("customers").insert({
          name: c.name, contact_name: c.contact_name ?? null, phone, email: c.email ?? null, region: c.region ?? null, tin: c.tin ?? null,
        }).select("id").single();
        if (ce) throw ce;

        const key = newLicenceKey();
        const { data: lic, error: le } = await sb.from("licences").insert({
          key_hash: await hashKey(key), key_hint: key.slice(-4), customer_id: cust.id,
          plan_code: planCode, extra_cameras: body.extra_cameras ?? 0, status: "active", notes: body.notes ?? null,
        }).select("id").single();
        if (le) throw le;
        await logEvent(sb, lic.id, "created", { by: user.email, plan_code: planCode });

        let payment = null;
        if (body.paid_months) payment = await recordManualPayment(sb, lic.id, planCode, Number(body.paid_months), body.method ?? "cash", phone, body.amount_tzs);

        // The plain key is shown ONCE here; only its hash is stored.
        return json({ licence_id: lic.id, licence_key: key, payment });
      }

      case "record_payment": {
        const { data: lic } = await sb.from("licences").select("id, plan_code, customer:customers(phone)").eq("id", body.licence_id).single();
        if (!lic) return json({ error: "licence not found" }, 404);
        const planCode = body.plan_code ?? lic.plan_code;
        const phone = normalisePhone(body.phone ?? (lic as any).customer?.phone ?? "") ?? "000000000000";
        const result = await recordManualPayment(sb, lic.id, planCode, Number(body.months ?? 1), body.method ?? "cash", phone, body.amount_tzs);
        return json(result);
      }

      // Test payments: marks a sandbox payment as paid, the same way a real gateway webhook will.
      case "confirm_sandbox_payment": {
        const { data: pay } = await sb.from("payments").select("id, gateway, status").eq("id", body.payment_id).single();
        if (!pay) return json({ error: "payment not found" }, 404);
        if (pay.gateway !== "sandbox") return json({ error: "Only sandbox payments can be confirmed by hand" }, 400);
        const { data, error } = await sb.rpc("apply_payment", { p_payment_id: pay.id });
        if (error) throw error;
        return json(data);
      }

      case "change_plan": {
        await sb.from("licences").update({ plan_code: body.plan_code, extra_cameras: body.extra_cameras ?? 0 }).eq("id", body.licence_id);
        await logEvent(sb, body.licence_id, "plan_changed", { by: user.email, plan_code: body.plan_code, extra_cameras: body.extra_cameras ?? 0 });
        return json({ ok: true });
      }

      case "revoke": {
        await sb.from("licences").update({ status: "revoked" }).eq("id", body.licence_id);
        await sb.from("devices").update({ active: false }).eq("licence_id", body.licence_id);
        await logEvent(sb, body.licence_id, "revoked", { by: user.email, reason: body.reason ?? null });
        return json({ ok: true });
      }

      case "reset_device": {
        await sb.from("devices").update({ active: false }).eq("licence_id", body.licence_id).eq("active", true);
        await logEvent(sb, body.licence_id, "device_reset", { by: user.email });
        return json({ ok: true, message: "The customer can now activate the key on a new computer." });
      }

      default:
        return json({ error: "Unknown action" }, 400);
    }
  } catch (e) {
    console.error(body.action, e);
    return json({ error: "server_error", detail: String((e as Error)?.message ?? e) }, 500);
  }
});

async function recordManualPayment(
  sb: ReturnType<typeof db>, licenceId: string, planCode: string, months: number,
  method: string, phone: string, amountOverride?: number,
) {
  if (![1, 12].includes(months)) throw new Error("months must be 1 or 12");
  const { data: plan } = await sb.from("plans").select("*").eq("code", planCode).single();
  const { data: lic } = await sb.from("licences").select("extra_cameras").eq("id", licenceId).single();
  const amount = amountOverride ?? priceFor(plan, months, lic?.extra_cameras ?? 0);
  const network = method === "bank" ? "bank" : "cash";
  const { data: pay, error } = await sb.from("payments").insert({
    licence_id: licenceId, plan_code: planCode, amount_tzs: amount, months, phone, network, gateway: "manual",
  }).select("id").single();
  if (error) throw error;
  const { data, error: ae } = await sb.rpc("apply_payment", { p_payment_id: pay.id });
  if (ae) throw ae;
  return { payment_id: pay.id, amount_tzs: amount, ...data };
}
