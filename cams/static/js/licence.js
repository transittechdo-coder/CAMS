// Licence & billing: the plan this computer has, free trial, licence key and mobile-money payment.
// Golden rule shown to users: recording, live view and fire alarms never stop because of payment.
import { h, get, post, icon, toast, fail, dialog, confirmBox, field } from "./util.js";
import { state, can, go } from "./app.js";

const tzs = (n) => `TZS ${Number(n || 0).toLocaleString("en-US")}`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");
const daysLeft = (iso) => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 864e5));

const STATE_TAG = {
  trial: ["Free trial", "teal"], active: ["Active", "teal"], due_soon: ["Renew soon", "amber"],
  grace: ["Payment overdue", "amber"], limited: ["Paid features locked", "red"], free: ["Free plan", ""],
  invalid: ["Needs attention", "red"],
};

// Tanzanian mobile-money network from the phone number (same rule as the licence server)
function network(phone) {
  let p = String(phone || "").replace(/\D/g, "");
  if (p.startsWith("255")) p = "0" + p.slice(3);
  if (p.length === 9) p = "0" + p;
  const pre = p.slice(0, 3);
  if (["074", "075", "076"].includes(pre)) return "M-Pesa";
  if (["068", "069", "078"].includes(pre)) return "Airtel Money";
  if (["065", "067", "071", "077"].includes(pre)) return "Mixx by Yas";
  if (["061", "062"].includes(pre)) return "HaloPesa";
  return "";
}

async function refreshLicence() {
  try { state.status.licence = await get("/api/licence"); } catch { /* ignore */ }
  window.dispatchEvent(new Event("hashchange"));
}

// ------------------------------------------------------------------ banner on every page
export function licenceBanner(page) {
  const l = state.status?.licence;
  if (!l?.banner || page === "licence") return null;
  const red = l.state === "limited" || l.state === "invalid";
  return h("div", { class: `banner licence-banner${red ? " red" : ""}` },
    h("span", { class: "grow" }, l.banner),
    h("button", { class: "small", onclick: () => go("licence") }, l.state === "trial" ? "See plans" : "Licence & billing"));
}

// ------------------------------------------------------------------ first start
export function maybeWelcome() {
  const l = state.status?.licence;
  if (!l || l.welcome_done || l.key_hint || !can("admin") || !l.enforced) return;
  const pick = (title, text, lines, action, primary) => h("button", { class: `licence-choice${primary ? " best" : ""}`, onclick: action },
    h("b", {}, title), h("span", { class: "hint" }, text), lines ? h("ul", {}, lines.map((x) => h("li", {}, x))) : null);
  const d = dialog({
    title: "Welcome to CAMS",
    wide: true,
    body: h("div", { class: "stack" },
      h("p", { class: "muted", style: { margin: 0 } }, "Choose how to start. You can change this any time in Licence & billing."),
      h("div", { class: "licence-choices" },
        pick("Try Premium free for 14 days", "Everything unlocked. Needs internet once.",
          ["Face recognition and Find a person", "Up to 16 cameras", "Campus map, routes and visitors"],
          async () => { d.close(); await startTrial(); }, true),
        pick("I have a licence key", "From Transit Tech, after paying.", null, () => { d.close(); enterKey(); }),
        pick("Use the Free plan", "No internet needed.",
          ["2 cameras", "Live view and recording", "Fire, smoke and person-down alarms"],
          async () => { d.close(); try { await post("/api/licence/welcome-done"); } catch {} refreshLicence(); })),
      h("p", { class: "hint", style: { margin: 0 } }, "Recording, live view and the fire alarms always keep working, even if a payment is late.")),
  });
}

async function startTrial() {
  try {
    state.status.licence = await post("/api/licence/trial");
    toast("Your 14-day Premium trial has started. Everything is unlocked.");
    refreshLicence();
  } catch (e) { fail(e); }
}

function enterKey() {
  const inp = h("input", { placeholder: "CAMS-XXXX-XXXX-XXXX-XXXX", autocomplete: "off", spellcheck: "false",
    style: { fontFamily: "var(--display)", letterSpacing: "1px", textTransform: "uppercase" } });
  inp.addEventListener("input", () => {
    let raw = inp.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (raw.startsWith("CAMS")) raw = raw.slice(4);
    raw = raw.slice(0, 16);
    inp.value = "CAMS" + (raw ? "-" + raw.match(/.{1,4}/g).join("-") : "");
  });
  const err = h("div", { class: "error-text", role: "alert" });
  dialog({
    title: "Enter your licence key",
    body: h("div", { class: "stack" },
      field("Licence key", inp, "It is on your receipt and in the SMS from Transit Tech. This computer needs internet for a moment."), err),
    actions: [{ label: "Cancel" }, { label: "Activate", class: "primary", run: async () => {
      err.textContent = "";
      try {
        state.status.licence = await post("/api/licence/activate", { licence_key: inp.value });
        toast(`Licence activated: ${state.status.licence.plan_name} plan`);
        refreshLicence();
      } catch (e) { err.textContent = e.message; return true; }
    } }],
  });
  setTimeout(() => inp.focus(), 50);
}

// ------------------------------------------------------------------ paying with mobile money
async function payDialog(plans, chosen = "pro") {
  const l = state.status.licence;
  if (!l.key_hint) {
    // a key is needed to pay; the free trial gives one
    try { state.status.licence = await post("/api/licence/trial"); }
    catch (e) { return fail(new Error(`${e.message} Ask Transit Tech for a licence key, then pay.`)); }
  }
  const paid = plans.filter((p) => p.code === "pro" || p.code === "premium");
  let plan = chosen, months = 12, timer = null;
  const body = h("div", { class: "stack" });
  const d = dialog({ title: "Pay with mobile money", body, onClose: () => clearInterval(timer) });

  const form = () => {
    const p = paid.find((x) => x.code === plan) || paid[0];
    const price = months === 12 ? p.yearly_price_tzs : p.monthly_price_tzs;
    const phone = h("input", { type: "tel", inputmode: "tel", placeholder: "0754 123 456", autocomplete: "tel" });
    const net = h("small", { class: "hint" }, "M-Pesa, Airtel Money, Mixx by Yas or HaloPesa.");
    phone.addEventListener("input", () => { const n = network(phone.value); net.textContent = n ? `${n} number` : "M-Pesa, Airtel Money, Mixx by Yas or HaloPesa."; });
    const err = h("div", { class: "error-text", role: "alert" });
    const send = h("button", { class: "primary" }, `Pay ${tzs(price)}`);
    send.onclick = async () => {
      err.textContent = "";
      if (!network(phone.value)) { err.textContent = "Enter a Tanzanian M-Pesa, Airtel Money, Mixx or HaloPesa number."; return; }
      send.disabled = true;
      try { waiting(await post("/api/licence/pay", { plan_code: plan, months, phone: phone.value }), phone.value); }
      catch (e) { err.textContent = e.message; send.disabled = false; }
    };
    body.replaceChildren(
      h("div", { class: "seg", "aria-label": "Plan" }, paid.map((x) => h("button", {
        "aria-pressed": String(x.code === plan),
        onclick: () => { plan = x.code; form(); } }, x.name))),
      h("div", { class: "seg", "aria-label": "How long" },
        h("button", { "aria-pressed": String(months === 1), onclick: () => { months = 1; form(); } }, `Monthly · ${tzs(p.monthly_price_tzs)}`),
        h("button", { "aria-pressed": String(months === 12), onclick: () => { months = 12; form(); } }, `Yearly · ${tzs(p.yearly_price_tzs)}`)),
      months === 12 ? h("p", { class: "hint", style: { margin: 0 } }, "Yearly gives you two months free.") : null,
      field("Phone number that will pay", phone), net, err,
      h("div", { class: "row end" }, h("button", { onclick: () => d.close() }, "Cancel"), send),
    );
    phone.focus();
  };

  const waiting = (res, phoneTyped) => {
    const until = Date.now() + 10 * 60e3;
    const left = h("b", { class: "num" }, "10:00");
    body.replaceChildren(h("div", { class: "licence-wait" },
      h("div", { class: "licence-phone", "aria-hidden": "true" }, icon("phone")),
      h("h3", {}, "Check your phone"),
      h("p", {}, `A payment request for ${tzs(res.amount_tzs)} was sent to ${phoneTyped}. Enter your ${network(phoneTyped) || "mobile money"} PIN to pay.`),
      h("p", { class: "hint" }, "Waiting for the payment... ", left),
      res.sandbox ? h("p", { class: "banner", style: { margin: 0 } }, "Test mode: no real money moves and no prompt reaches the phone yet. Transit Tech confirms test payments.") : null,
      h("div", { class: "row end" }, h("button", { onclick: () => d.close() }, "Close"))));
    timer = setInterval(async () => {
      const s = Math.max(0, Math.round((until - Date.now()) / 1000));
      left.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      if (s % 5) return;
      try {
        const r = await get(`/api/licence/pay/${res.payment_id}`);
        if (r.status === "paid") { clearInterval(timer); state.status.licence = r.licence; done(r); }
        else if (r.status === "failed" || s === 0) { clearInterval(timer); failed(); }
      } catch { /* offline for a moment: keep waiting */ }
    }, 1000);
  };

  const done = (r) => {
    const l2 = r.licence;
    body.replaceChildren(h("div", { class: "licence-wait ok" },
      h("div", { class: "licence-phone", "aria-hidden": "true" }, "✓"),
      h("h3", {}, "Paid. Thank you!"),
      h("p", {}, `Your ${l2.plan_name} plan now runs until ${day(l2.paid_until)}.`),
      r.receipt_no ? h("p", { class: "hint" }, `Receipt number ${r.receipt_no}`) : null,
      h("div", { class: "row end" }, h("button", { class: "primary", onclick: () => d.close() }, "Done"))));
    refreshLicence();
  };

  const failed = () => {
    body.replaceChildren(h("div", { class: "licence-wait" },
      h("h3", {}, "Payment not completed"),
      h("p", {}, "The PIN was not entered in time, or the payment was cancelled. No money was taken."),
      h("div", { class: "row end" }, h("button", { onclick: () => d.close() }, "Close"), h("button", { class: "primary", onclick: form }, "Try again"))));
  };

  form();
}

// ------------------------------------------------------------------ the page
export async function licencePage(el) {
  const [l, { plans, feature_names: names }] = await Promise.all([get("/api/licence"), get("/api/licence/plans")]);
  state.status.licence = l;
  const admin = can("admin");
  const [tagText, tagClass] = STATE_TAG[l.state] || [l.state, ""];

  el.append(h("div", { class: "page-head" },
    h("div", { class: "grow" }, h("h1", {}, "Licence & billing"),
      h("p", {}, "Your plan, free trial and payments. Recording, live view and the fire alarms always keep working, even if a payment is late."))));

  // ---- current plan
  const lines = [];
  lines.push(["Cameras", l.max_cameras == null ? `${l.cameras_used} (no limit)` : `${l.cameras_used} of ${l.max_cameras}`]);
  if (l.state === "trial") lines.push(["Trial ends", `${day(l.trial_ends_at)} (${daysLeft(l.trial_ends_at)} days left)`]);
  if (l.paid_until) lines.push([l.state === "limited" ? "Paid until (ended)" : "Paid until", day(l.paid_until)]);
  if (l.state === "grace" && l.grace_until) lines.push(["Paid features lock on", day(l.grace_until)]);
  lines.push(["Licence key", l.key_hint || "None on this computer"]);

  const act = [];
  if (admin) {
    if (!l.key_hint) {
      act.push(h("button", { class: "primary", onclick: startTrial }, "Start 14-day free trial"));
      act.push(h("button", { onclick: enterKey }, "Enter a licence key"));
    } else {
      act.push(h("button", { class: "primary", onclick: () => payDialog(plans, l.paid_plan === "premium" || l.state === "trial" ? "premium" : "pro") },
        l.state === "trial" || l.state === "free" ? "Choose a plan and pay" : "Pay / renew"));
      act.push(h("button", { onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { state.status.licence = await post("/api/licence/renew"); toast("Licence checked with Transit Tech"); refreshLicence(); }
        catch (x) { fail(x); e.currentTarget.disabled = false; }
      } }, "Check now"));
      act.push(h("button", { onclick: enterKey }, "Enter a different key"));
      act.push(h("button", { class: "ghost", onclick: async () => {
        if (!(await confirmBox("Move the licence to another computer?",
          "This computer goes back to the Free plan (recording keeps working). Then enter the same key on the new computer.", "Move licence"))) return;
        try { const r = await post("/api/licence/deactivate"); toast(r.message); refreshLicence(); } catch (x) { fail(x); }
      } }, "Move to another computer"));
    }
  }

  el.append(h("section", { class: "panel licence-now", style: { marginBottom: "16px" } },
    h("div", { class: "panel-head" }, h("h2", {}, "Your plan"), h("span", { class: `tag ${tagClass}` }, tagText)),
    h("div", { class: "panel-body stack" },
      h("div", { class: "licence-plan-name" }, l.plan_name),
      l.message ? h("p", { class: "banner red", style: { margin: 0 } }, l.message) : null,
      l.needs_online_check && !l.message ? h("p", { class: "banner", style: { margin: 0 } }, "Connect this computer to the internet once so CAMS can check its licence.") : null,
      h("dl", { class: "licence-facts" }, lines.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      admin ? h("div", { class: "row" }, act) : h("p", { class: "hint", style: { margin: 0 } }, "Only a CAMS admin can change the licence or pay."),
      !l.enforced ? h("p", { class: "hint", style: { margin: 0 } }, "Developer mode: plan limits are switched off on this computer (CAMS_LICENCE_ENFORCE=0).") : null)));

  // ---- plans side by side
  const shown = plans.filter((p) => ["free", "pro", "premium"].includes(p.code));
  const allFeatures = [...new Set(shown.flatMap((p) => p.features))];
  el.append(h("section", { class: "panel", style: { marginBottom: "16px" } },
    h("div", { class: "panel-head" }, h("h2", {}, "Plans")),
    h("div", { class: "panel-body" },
      h("div", { class: "licence-plans" }, shown.map((p) => {
        const mine = p.code === l.plan && l.state !== "free" && l.state !== "limited" ? true : p.code === "free" && (l.state === "free" || l.state === "limited");
        return h("div", { class: `licence-card${mine ? " mine" : ""}${p.code === "premium" ? " best" : ""}` },
          h("div", { class: "licence-card-head" }, h("b", {}, p.name), mine ? h("span", { class: "tag teal" }, "Your plan") : null),
          h("div", { class: "licence-price" }, h("span", {}, h("b", { class: "num" }, tzs(p.monthly_price_tzs)), p.monthly_price_tzs ? " a month" : "")),
          p.yearly_price_tzs ? h("div", { class: "hint" }, `or ${tzs(p.yearly_price_tzs)} a year (2 months free)`) : h("div", { class: "hint" }, "No time limit"),
          h("div", { class: "hint" }, `${p.max_cameras == null ? "Any number of" : `Up to ${p.max_cameras}`} cameras · ${p.max_phones ? `${p.max_phones} guard phone${p.max_phones > 1 ? "s" : ""}` : "no guard phones"}`),
          h("ul", { class: "licence-feats" }, allFeatures.map((f) => h("li", { class: p.features.includes(f) ? "yes" : "no" }, names[f] || f))),
          admin && p.code !== "free" ? h("button", { class: p.code === "premium" ? "primary" : "", onclick: () => payDialog(plans, p.code) }, `Choose ${p.name}`) : null);
      })),
      h("p", { class: "hint", style: { margin: "12px 0 0" } }, "Big sites with more than 16 cameras or several buildings: ask Transit Tech for an Enterprise plan. Installation and training are quoted after a site visit."))));
}
