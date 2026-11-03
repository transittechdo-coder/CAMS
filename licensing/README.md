# CAMS Licensing & Payments

The licence server for CAMS (Camera AI Management System) by Transit Tech, plus the Python module the desktop app uses to check licences offline.

## What is live

- **Supabase project:** `cams-licence` (eu-central-1)
- **Licence API (for the CAMS app):** `https://iezaqksdtuyiahtcfbzk.supabase.co/functions/v1/licence-api`
- **Admin API (for Transit Tech):** `https://iezaqksdtuyiahtcfbzk.supabase.co/functions/v1/admin-api`
- **Public signing key** (already inside `cams_licence.py`): `9huIc3Kw6AF+d+7+xm3Tc/i8S454Mnof5nzNS3vdv1c=`

The private signing key was created on the server and never leaves the database.

## Golden rule

Live view, recording and emergency alerts never switch off because of payment. Only paid features lock.

## Plans (stored in the `plans` table)

| Plan | Cameras | Guard phones |
| --- | --- | --- |
| Free | 2 | 0 |
| Pro | 6 | 1 |
| Premium | 16 | 5 |
| Enterprise | No limit | No limit |

Prices are in the `plans` table and can be changed there without touching code.

## Using it in CAMS

```bash
pip install cryptography requests
```

```python
from cams import licence as lic

status = lic.check_licence()          # offline, on start-up and every hour
if status.has("face_recognition"):
    ...                               # show the feature
print(status.banner)                  # text for the top banner, or None

lic.start_trial()                     # first start, "Start 14-day free trial"
lic.activate("CAMS-XXXX-XXXX-XXXX-XXXX")
lic.renew()                           # quietly every 7 days

pay = lic.start_payment("pro", 12, "0754123456")   # sends USSD push
lic.payment_status(pay["payment_id"])               # poll every 5 s: pending / paid / failed
```

## Licence API actions (POST JSON with `action`)

| Action | Needs | Returns |
| --- | --- | --- |
| `plans` | nothing | plan list with prices |
| `public_key` | nothing | Ed25519 public key |
| `start_trial` | fingerprint | new key + signed licence file |
| `activate` | licence_key, fingerprint | signed licence file |
| `renew` | licence_key, fingerprint | fresh signed licence file |
| `deactivate` | licence_key, fingerprint | ok (frees the key for another computer) |
| `start_payment` | licence_key, fingerprint, plan_code, months (1 or 12), phone | payment_id, amount_tzs |
| `payment_status` | licence_key, fingerprint, payment_id | status, and a new licence file when paid |

## Admin API actions (signed-in admin only)

`dashboard`, `list_licences`, `licence_detail`, `create_licence`, `record_payment` (cash/bank), `confirm_sandbox_payment`, `change_plan`, `revoke`, `reset_device`.

To make yourself admin: create a user in Supabase Auth, then run
`insert into public.admins (user_id) values ('<your user id>');` in the SQL editor.

## Not done yet

- **Real mobile-money gateway.** Payments run in `sandbox` mode: no USSD push is sent and test payments are confirmed with `confirm_sandbox_payment`. Once you pick a gateway (ZenoPay, Selcom, AzamPay, ClickPesa…), its USSD-push call goes in `sendUssdPush()` and a `payment-webhook` function is added.
- **SMS** with the key and receipt.
- **Admin dashboard web page** on top of the admin API.
- **Licence screens inside CAMS** (Welcome, Enter key, Licence & Billing, Pay, banners).
