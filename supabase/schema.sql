-- Run this in Supabase SQL Editor (Dashboard → SQL → New query)

-- Alerts table: one row per violence detection
create table if not exists public.violence_alerts (
  id uuid primary key default gen_random_uuid(),
  detected_at timestamptz not null default now(),
  camera_ip text,
  channel int default 1,
  confidence real not null,
  label text not null default 'violence',
  snapshot_path text,
  clip_path text,
  snapshot_url text,
  cloudinary_public_id text,
  message text,
  whatsapp_status text default 'pending',  -- pending | sent | failed | skipped
  whatsapp_error text,
  created_at timestamptz not null default now()
);

create index if not exists violence_alerts_detected_at_idx
  on public.violence_alerts (detected_at desc);

-- Allow inserts from the monitor (service role bypasses RLS;
-- anon key can insert if you enable the policy below)
alter table public.violence_alerts enable row level security;

create policy "Allow insert alerts"
  on public.violence_alerts
  for insert
  to anon, authenticated
  with check (true);

create policy "Allow read alerts"
  on public.violence_alerts
  for select
  to anon, authenticated
  using (true);

create policy "Allow update whatsapp status"
  on public.violence_alerts
  for update
  to anon, authenticated
  using (true)
  with check (true);

-- Snapshot files for the daycare portal (public read, service-role write)
insert into storage.buckets (id, name, public)
values ('detections', 'detections', true)
on conflict (id) do update set public = excluded.public;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'Public read detection frames'
  ) then
    create policy "Public read detection frames"
      on storage.objects
      for select
      to public
      using (bucket_id = 'detections');
  end if;
end $$;

-- Optional: notify Edge Function via Database Webhook
-- Dashboard → Database → Webhooks → Create a new hook
--   Table: violence_alerts
--   Events: INSERT
--   Type: Supabase Edge Functions
--   Function: send-violence-whatsapp
--
-- Or call the Edge Function directly from Python (already supported).
