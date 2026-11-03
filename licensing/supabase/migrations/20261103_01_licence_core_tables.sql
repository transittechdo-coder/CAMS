-- Applied to project cams-licence on 2026-11-03. See README.md.
create table public.plans (
  code text primary key check (code in ('free','pro','premium','enterprise')),
  name text not null,
  monthly_price_tzs integer not null check (monthly_price_tzs >= 0),
  yearly_price_tzs integer check (yearly_price_tzs >= 0),
  max_cameras integer,
  max_phones integer,
  extra_camera_price_tzs integer,
  features text[] not null default '{}',
  sort_order smallint not null default 0
);
create table public.customers (
  id uuid primary key default gen_random_uuid(),
  name text not null, contact_name text, phone text not null, email text, region text, tin text,
  created_at timestamptz not null default now()
);
create index customers_phone_idx on public.customers (phone);
create table public.licences (
  id uuid primary key default gen_random_uuid(),
  key_hash text unique not null,
  key_hint text not null,
  customer_id uuid references public.customers(id) on delete set null,
  plan_code text not null references public.plans(code),
  extra_cameras integer not null default 0 check (extra_cameras >= 0),
  status text not null default 'trial' check (status in ('trial','active','suspended','revoked')),
  trial_ends_at timestamptz, paid_until timestamptz,
  device_moves_this_year integer not null default 0,
  notes text,
  created_at timestamptz not null default now()
);
create index licences_customer_idx on public.licences (customer_id);
create index licences_plan_idx on public.licences (plan_code);
create table public.devices (
  id uuid primary key default gen_random_uuid(),
  licence_id uuid not null references public.licences(id) on delete cascade,
  fingerprint_hash text not null, computer_name text, cams_version text,
  activated_at timestamptz not null default now(), last_seen_at timestamptz,
  active boolean not null default true
);
create unique index devices_one_active_per_licence on public.devices (licence_id) where active;
create index devices_licence_idx on public.devices (licence_id);
create index devices_fingerprint_idx on public.devices (fingerprint_hash);
create table public.payments (
  id uuid primary key default gen_random_uuid(),
  licence_id uuid not null references public.licences(id) on delete cascade,
  plan_code text not null references public.plans(code),
  amount_tzs integer not null check (amount_tzs > 0),
  months integer not null check (months in (1, 12)),
  phone text not null,
  network text check (network in ('mpesa','airtel','mixx','halopesa','cash','bank')),
  gateway text not null, gateway_ref text unique,
  status text not null default 'pending' check (status in ('pending','paid','failed','cancelled')),
  created_at timestamptz not null default now(), paid_at timestamptz
);
create index payments_licence_idx on public.payments (licence_id);
create index payments_plan_idx on public.payments (plan_code);
create index payments_status_created_idx on public.payments (status, created_at desc);
create sequence public.receipt_seq;
create table public.receipts (
  id uuid primary key default gen_random_uuid(),
  payment_id uuid unique not null references public.payments(id) on delete cascade,
  receipt_no text unique not null, amount_tzs integer not null,
  issued_at timestamptz not null default now(), pdf_url text
);
create table public.licence_events (
  id bigint generated always as identity primary key,
  licence_id uuid references public.licences(id) on delete cascade,
  event text not null, details jsonb, created_at timestamptz not null default now()
);
create index licence_events_licence_idx on public.licence_events (licence_id, created_at desc);
create table public.activation_attempts (
  id bigint generated always as identity primary key,
  fingerprint_hash text not null, ok boolean not null, created_at timestamptz not null default now()
);
create index activation_attempts_fp_idx on public.activation_attempts (fingerprint_hash, created_at desc);
create table public.admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
alter table public.plans enable row level security;
alter table public.customers enable row level security;
alter table public.licences enable row level security;
alter table public.devices enable row level security;
alter table public.payments enable row level security;
alter table public.receipts enable row level security;
alter table public.licence_events enable row level security;
alter table public.activation_attempts enable row level security;
alter table public.admins enable row level security;
create policy "Anyone can read plans" on public.plans for select to anon, authenticated using (true);

create or replace function public.apply_payment(p_payment_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_pay public.payments%rowtype; v_lic public.licences%rowtype;
  v_base timestamptz; v_new timestamptz; v_receipt text;
begin
  select * into v_pay from public.payments where id = p_payment_id for update;
  if not found then raise exception 'payment not found'; end if;
  if v_pay.status = 'paid' then return jsonb_build_object('already_paid', true, 'payment_id', v_pay.id); end if;
  select * into v_lic from public.licences where id = v_pay.licence_id for update;
  v_base := greatest(now(), coalesce(v_lic.paid_until, now()));
  v_new := v_base + make_interval(months => v_pay.months);
  update public.payments set status = 'paid', paid_at = now() where id = v_pay.id;
  update public.licences set paid_until = v_new, plan_code = v_pay.plan_code, status = 'active' where id = v_lic.id;
  v_receipt := 'TT-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('public.receipt_seq')::text, 5, '0');
  insert into public.receipts (payment_id, receipt_no, amount_tzs) values (v_pay.id, v_receipt, v_pay.amount_tzs);
  insert into public.licence_events (licence_id, event, details)
  values (v_lic.id, 'paid', jsonb_build_object('payment_id', v_pay.id, 'months', v_pay.months, 'paid_until', v_new, 'receipt_no', v_receipt));
  return jsonb_build_object('already_paid', false, 'paid_until', v_new, 'receipt_no', v_receipt);
end; $$;
revoke all on function public.apply_payment(uuid) from public, anon, authenticated;
grant execute on function public.apply_payment(uuid) to service_role;

insert into public.plans (code, name, monthly_price_tzs, yearly_price_tzs, max_cameras, max_phones, extra_camera_price_tzs, features, sort_order) values
 ('free', 'Free', 0, 0, 2, 0, null, '{live_view,recording,clip_download,emergency_alerts}', 1),
 ('pro', 'Pro', 50000, 500000, 6, 1, 8000, '{live_view,recording,clip_download,emergency_alerts,motion_alerts,clip_export,daily_report,guard_app}', 2),
 ('premium', 'Premium', 150000, 1500000, 16, 5, 6000, '{live_view,recording,clip_download,emergency_alerts,motion_alerts,clip_export,daily_report,guard_app,face_recognition,last_seen_search,restricted_zones,building_map,routes,visitor_checkin,number_plates,bag_left_behind}', 3),
 ('enterprise', 'Enterprise', 400000, 4000000, null, null, null, '{live_view,recording,clip_download,emergency_alerts,motion_alerts,clip_export,daily_report,guard_app,face_recognition,last_seen_search,restricted_zones,building_map,routes,visitor_checkin,number_plates,bag_left_behind,multi_site,priority_support}', 4);
