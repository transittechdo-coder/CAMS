create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
create table private.signing_keys (
  id smallint primary key default 1 check (id = 1),
  private_pkcs8_b64 text not null, public_raw_b64 text not null,
  created_at timestamptz not null default now()
);
create or replace function public.get_signing_key()
returns table (private_pkcs8_b64 text, public_raw_b64 text)
language sql security definer set search_path = '' as $$
  select k.private_pkcs8_b64, k.public_raw_b64 from private.signing_keys k where k.id = 1;
$$;
create or replace function public.set_signing_key(p_private text, p_public text)
returns void language sql security definer set search_path = '' as $$
  insert into private.signing_keys (id, private_pkcs8_b64, public_raw_b64)
  values (1, p_private, p_public) on conflict (id) do nothing;
$$;
revoke all on function public.get_signing_key() from public, anon, authenticated;
revoke all on function public.set_signing_key(text, text) from public, anon, authenticated;
grant execute on function public.get_signing_key() to service_role;
grant execute on function public.set_signing_key(text, text) to service_role;
