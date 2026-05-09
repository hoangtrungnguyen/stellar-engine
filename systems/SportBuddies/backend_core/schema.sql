-- =============================================================================
-- SportBuddies (SpB) — Master DDL
-- Target: PostgreSQL 15+ (Supabase)
-- Run via: supabase db push
-- Last updated: 2026-05-06
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------

-- earthdistance requires cube; cascade installs it automatically
create extension if not exists cube;
create extension if not exists earthdistance;   -- ll_to_earth(), earth_distance()
create extension if not exists pg_cron;          -- background job scheduling

-- Note: gen_random_uuid() is built-in since PostgreSQL 13; no uuid-ossp needed.
-- Note: auth.uid() and auth.users are Supabase-specific. RLS policies that
--       reference auth.uid() require Supabase Auth to be enabled.

-- ---------------------------------------------------------------------------
-- 1. Tables (dependency order)
-- ---------------------------------------------------------------------------

-- 1.1 Users -------------------------------------------------------------------
-- Mirrors auth.users; populated by trigger on_auth_user_created (section 4).
create table if not exists public.users (
  id                  uuid        primary key references auth.users (id) on delete cascade,
  phone               text,
  email               text,
  full_name           text,
  avatar_url          text,
  role                text        not null default 'player'
                                  check (role in ('player', 'owner', 'agent', 'admin')),
  fcm_tokens          text[]      not null default '{}',
  last_lat            float8,
  last_lng            float8,
  location_updated_at timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- 1.2 Courts ------------------------------------------------------------------
create table if not exists public.courts (
  id              uuid        primary key default gen_random_uuid(),
  owner_id        uuid        not null references public.users (id),
  name            text        not null,
  address         text        not null,
  lat             float8,                        -- null when geocoding fails
  lng             float8,                        -- float8 required by ll_to_earth()
  sport_types     text[]      not null default '{}',
  capacity        integer,
  amenities       text[]      not null default '{}',
  price_per_hour  numeric     not null,
  operating_hours jsonb       not null default '{}',
  photos          text[]      not null default '{}',
  description     text,
  status          text        not null default 'pending'
                              check (status in ('pending', 'approved', 'suspended')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- 1.3 Recurrence rules --------------------------------------------------------
create table if not exists public.recurrence_rules (
  id           uuid    primary key default gen_random_uuid(),
  court_id     uuid    not null references public.courts (id) on delete cascade,
  days_of_week integer[] not null,               -- 0=Sun … 6=Sat
  start_time   time    not null,
  end_time     time    not null,
  valid_from   date    not null,
  valid_until  date,                             -- null = indefinite
  is_active    boolean not null default true,
  created_by   uuid    references public.users (id),
  created_at   timestamptz not null default now()
);

-- 1.4 Slots -------------------------------------------------------------------
create table if not exists public.slots (
  id                 uuid        primary key default gen_random_uuid(),
  court_id           uuid        not null references public.courts (id) on delete cascade,
  start_at           timestamptz not null,
  end_at             timestamptz not null,
  status             text        not null default 'open'
                                 check (status in ('open', 'booked', 'blocked', 'maintenance')),
  access_policy      text        not null default 'private'
                                 check (access_policy in ('private', 'open')),
  max_players        integer,
  blocked_reason     text,
  is_owner_slot      boolean     not null default false,
  is_recurring       boolean     not null default false,
  recurrence_rule_id uuid        references public.recurrence_rules (id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint unique_court_start unique (court_id, start_at)
);

-- 1.5 Bookings ----------------------------------------------------------------
create table if not exists public.bookings (
  id                uuid        primary key default gen_random_uuid(),
  slot_id           uuid        not null references public.slots (id),
  user_id           uuid        references public.users (id),   -- null for walk-ins
  court_id          uuid        not null references public.courts (id),
  customer_name     text,
  customer_phone    text,
  notes             text,
  status            text        not null default 'pending'
                                check (status in ('pending', 'confirmed', 'cancelled', 'completed', 'no_show')),
  price_per_hour    numeric     not null,
  duration_minutes  integer     not null,
  total_price       numeric     not null,
  is_owner_slot     boolean     not null default false,
  is_walk_in        boolean     not null default false,
  override_reason   text,
  reminder_sent     boolean     not null default false,
  owner_response_at timestamptz,
  completed_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- 1.6 Slot participants -------------------------------------------------------
create table if not exists public.slot_participants (
  id             uuid        primary key default gen_random_uuid(),
  slot_id        uuid        not null references public.slots (id) on delete cascade,
  user_id        uuid        not null references public.users (id),
  joined_at      timestamptz not null default now(),
  payment_status text        not null default 'unpaid'
                             check (payment_status in ('paid', 'unpaid', 'partial')),
  payment_method text        check (payment_method in ('cash', 'transfer', 'app_wallet')),
  constraint unique_slot_user unique (slot_id, user_id)
);

-- 1.7 Slot join requests ------------------------------------------------------
create table if not exists public.slot_join_requests (
  id           uuid        primary key default gen_random_uuid(),
  slot_id      uuid        not null references public.slots (id) on delete cascade,
  user_id      uuid        not null references public.users (id),
  status       text        not null default 'pending'
                           check (status in ('pending', 'approved', 'rejected')),
  requested_at timestamptz not null default now(),
  constraint unique_slot_join_request unique (slot_id, user_id)
);

-- 1.8 Notifications -----------------------------------------------------------
create table if not exists public.notifications (
  id                 uuid        primary key default gen_random_uuid(),
  user_id            uuid        not null references public.users (id) on delete cascade,
  type               text        not null,
  title              text        not null,
  body               text        not null,
  data               jsonb       not null default '{}',
  read               boolean     not null default false,
  read_at            timestamptz,
  related_booking_id uuid        references public.bookings (id),
  related_slot_id    uuid        references public.slots (id),
  created_at         timestamptz not null default now()
);

-- 1.9 Skill ratings -----------------------------------------------------------
create table if not exists public.skill_ratings (
  id        uuid        primary key default gen_random_uuid(),
  player_id uuid        not null references public.users (id) on delete cascade,
  sport     text        not null,
  level     text        not null
                        check (level in ('beginner', 'intermediate', 'advanced', 'professional')),
  rated_by  uuid        not null references public.users (id),
  rated_at  timestamptz not null default now(),
  constraint unique_player_sport_rating unique (player_id, sport)
);

-- 1.10 Slot push log ----------------------------------------------------------
create table if not exists public.slot_push_log (
  id      uuid        primary key default gen_random_uuid(),
  slot_id uuid        not null references public.slots (id) on delete cascade,
  user_id uuid        not null references public.users (id),
  sent_at timestamptz not null default now(),
  constraint unique_slot_push unique (slot_id, user_id)
);

-- 1.11 Leads ------------------------------------------------------------------
create table if not exists public.leads (
  id           uuid        primary key default gen_random_uuid(),
  type         text        not null default 'owner'
                           check (type in ('owner')),
  name         text,
  phone        text        not null,
  court_name   text,
  sport_types  text[]      not null default '{}',
  district     text,
  agent_code   text,
  utm_source   text,
  utm_medium   text,
  utm_campaign text,
  status       text        not null default 'pending'
                           check (status in ('pending', 'contacted', 'onboarded', 'active', 'inactive')),
  notes        text,
  created_at   timestamptz not null default now()
);

-- 1.12 Agent applications -----------------------------------------------------
create table if not exists public.agent_applications (
  id                  uuid        primary key default gen_random_uuid(),
  full_name           text        not null,
  phone               text        not null,
  role                text        not null
                                  check (role in ('coach', 'group_admin', 'gym_owner', 'sports_shop', 'other')),
  network_description text,
  agent_code          text        unique,
  status              text        not null default 'pending'
                                  check (status in ('pending', 'contacted', 'active', 'inactive')),
  utm_source          text,
  utm_medium          text,
  utm_campaign        text,
  created_at          timestamptz not null default now()
);

-- 1.13 Commission rules -------------------------------------------------------
create table if not exists public.commission_rules (
  id              uuid    primary key default gen_random_uuid(),
  amount_vnd      integer not null default 200000,
  min_active_days integer not null default 30,
  effective_from  date    not null default current_date,
  created_at      timestamptz not null default now()
);

insert into public.commission_rules (amount_vnd, min_active_days, effective_from)
values (200000, 30, current_date)
on conflict do nothing;

-- 1.14 Commission payouts -----------------------------------------------------
create table if not exists public.commission_payouts (
  id          uuid        primary key default gen_random_uuid(),
  agent_id    uuid        not null references public.users (id),
  period      text        not null,              -- 'YYYY-MM'
  amount_vnd  integer     not null,
  court_count integer     not null,
  paid_at     timestamptz not null default now(),
  paid_by     uuid        references public.users (id)
);

-- ---------------------------------------------------------------------------
-- 2. Indexes
-- ---------------------------------------------------------------------------

-- courts
create index if not exists idx_courts_owner_id  on public.courts (owner_id);
create index if not exists idx_courts_status     on public.courts (status);
-- Proximity search via earthdistance; lat/lng must be float8 for ll_to_earth()
create index if not exists idx_courts_geo
  on public.courts using gist (ll_to_earth(lat, lng))
  where lat is not null and lng is not null;

-- slots
create index if not exists idx_slots_court_start    on public.slots (court_id, start_at);
create index if not exists idx_slots_court_start_st on public.slots (court_id, start_at, status);
create index if not exists idx_slots_status_start   on public.slots (status, start_at);

-- bookings
create index if not exists idx_bookings_slot_id       on public.bookings (slot_id);
create index if not exists idx_bookings_slot_status   on public.bookings (slot_id, status);
create index if not exists idx_bookings_user_id       on public.bookings (user_id);
create index if not exists idx_bookings_court_id      on public.bookings (court_id);
create index if not exists idx_bookings_status_start  on public.bookings (status, created_at);
-- Cron: reminder — query confirmed bookings where reminder not yet sent
create index if not exists idx_bookings_reminder
  on public.bookings (status, reminder_sent)
  where status = 'confirmed' and reminder_sent = false;

-- notifications
create index if not exists idx_notifications_user_read on public.notifications (user_id, read);
create index if not exists idx_notifications_user_time on public.notifications (user_id, created_at desc);

-- slot_join_requests
create index if not exists idx_join_req_slot_status on public.slot_join_requests (slot_id, status);

-- leads
create index if not exists idx_leads_agent_code on public.leads (agent_code);
create index if not exists idx_leads_status     on public.leads (status);

-- agent_applications
create index if not exists idx_agent_apps_phone      on public.agent_applications (phone);
create index if not exists idx_agent_apps_agent_code on public.agent_applications (agent_code);
create index if not exists idx_agent_apps_status     on public.agent_applications (status);

-- commission_payouts
create index if not exists idx_commission_payouts_agent on public.commission_payouts (agent_id, period);

-- ---------------------------------------------------------------------------
-- 3. Row-Level Security (RLS)
-- ---------------------------------------------------------------------------

alter table public.users              enable row level security;
alter table public.courts             enable row level security;
alter table public.recurrence_rules   enable row level security;
alter table public.slots              enable row level security;
alter table public.bookings           enable row level security;
alter table public.slot_participants  enable row level security;
alter table public.slot_join_requests enable row level security;
alter table public.notifications      enable row level security;
alter table public.skill_ratings      enable row level security;
alter table public.slot_push_log      enable row level security;
alter table public.leads              enable row level security;
alter table public.agent_applications enable row level security;
alter table public.commission_rules   enable row level security;
alter table public.commission_payouts enable row level security;

-- users
create policy "users_read_own"
  on public.users for select
  using (auth.uid() = id);

create policy "users_update_own"
  on public.users for update
  using (auth.uid() = id);

-- courts
create policy "courts_read_approved"
  on public.courts for select
  using (status = 'approved');

create policy "courts_owner_all"
  on public.courts for all
  using (auth.uid() = owner_id);

-- recurrence_rules
create policy "recurrence_owner_all"
  on public.recurrence_rules for all
  using (
    exists (
      select 1 from public.courts c
      where c.id = court_id and c.owner_id = auth.uid()
    )
  );

-- slots
create policy "slots_read_public"
  on public.slots for select
  using (
    status in ('open', 'booked')
    and exists (
      select 1 from public.courts c
      where c.id = court_id and c.status = 'approved'
    )
  );

create policy "slots_owner_all"
  on public.slots for all
  using (
    exists (
      select 1 from public.courts c
      where c.id = court_id and c.owner_id = auth.uid()
    )
  );

-- bookings
create policy "bookings_player_read"
  on public.bookings for select
  using (auth.uid() = user_id);

create policy "bookings_player_insert"
  on public.bookings for insert
  with check (auth.uid() = user_id);

create policy "bookings_player_cancel"
  on public.bookings for update
  using (auth.uid() = user_id and status = 'pending');

create policy "bookings_owner_read"
  on public.bookings for select
  using (
    exists (
      select 1 from public.slots s
      join public.courts c on c.id = s.court_id
      where s.id = slot_id and c.owner_id = auth.uid()
    )
  );

create policy "bookings_owner_update"
  on public.bookings for update
  using (
    exists (
      select 1 from public.slots s
      join public.courts c on c.id = s.court_id
      where s.id = slot_id and c.owner_id = auth.uid()
    )
  );

-- slot_participants
create policy "slot_participants_read"
  on public.slot_participants for select
  using (
    auth.uid() = user_id
    or exists (
      select 1 from public.slots s
      join public.courts c on c.id = s.court_id
      where s.id = slot_id and c.owner_id = auth.uid()
    )
  );

create policy "slot_participants_owner_insert"
  on public.slot_participants for insert
  with check (
    exists (
      select 1 from public.slots s
      join public.courts c on c.id = s.court_id
      where s.id = slot_id and c.owner_id = auth.uid()
    )
  );

-- slot_join_requests
create policy "join_requests_requester_read"
  on public.slot_join_requests for select
  using (auth.uid() = user_id);

create policy "join_requests_requester_insert"
  on public.slot_join_requests for insert
  with check (auth.uid() = user_id);

create policy "join_requests_owner_all"
  on public.slot_join_requests for all
  using (
    exists (
      select 1 from public.slots s
      join public.courts c on c.id = s.court_id
      where s.id = slot_id and c.owner_id = auth.uid()
    )
  );

-- notifications
create policy "notifications_read_own"
  on public.notifications for select
  using (auth.uid() = user_id);

create policy "notifications_update_own"
  on public.notifications for update
  using (auth.uid() = user_id);

-- skill_ratings
create policy "skill_ratings_read"
  on public.skill_ratings for select
  using (true);

create policy "skill_ratings_owner_write"
  on public.skill_ratings for all
  using (
    auth.uid() = rated_by
    and exists (
      select 1 from public.bookings b
      join public.slots s  on s.id = b.slot_id
      join public.courts c on c.id = s.court_id
      where b.user_id = player_id
        and c.owner_id = auth.uid()
        and b.status = 'completed'
    )
  );

-- leads: landing page form submits anonymously
create policy "leads_public_insert"
  on public.leads for insert
  with check (true);

-- agent_applications: registration form submits anonymously
create policy "agent_apps_public_insert"
  on public.agent_applications for insert
  with check (true);

-- commission_rules: all authenticated users can read
create policy "commission_rules_read"
  on public.commission_rules for select
  using (true);

-- commission_payouts: agent reads own payouts only
create policy "commission_payouts_agent_read"
  on public.commission_payouts for select
  using (auth.uid() = agent_id);

-- ---------------------------------------------------------------------------
-- 4. Functions & Triggers
-- ---------------------------------------------------------------------------

-- 4.1 Populate public.users on Supabase Auth sign-up
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.users (id, email, phone)
  values (
    new.id,
    new.email,
    new.raw_user_meta_data ->> 'phone'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 4.2 updated_at maintenance
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger trg_users_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

create trigger trg_courts_updated_at
  before update on public.courts
  for each row execute function public.set_updated_at();

create trigger trg_slots_updated_at
  before update on public.slots
  for each row execute function public.set_updated_at();

create trigger trg_bookings_updated_at
  before update on public.bookings
  for each row execute function public.set_updated_at();

-- 4.3 Atomic booking — SELECT FOR UPDATE prevents concurrent double-booking
create or replace function public.create_booking(
  p_slot_id        uuid,
  p_user_id        uuid,
  p_notes          text    default null,
  p_customer_name  text    default null,
  p_customer_phone text    default null
)
returns public.bookings
language plpgsql
security definer
set search_path = public
as $$
declare
  v_slot    public.slots;
  v_court   public.courts;
  v_booking public.bookings;
  v_dur_min integer;
begin
  -- Lock the slot row; fails immediately if another transaction holds the lock
  select * into v_slot
  from public.slots
  where id = p_slot_id and status = 'open'
  for update nowait;

  if not found then
    raise exception 'slot_unavailable'
      using hint = 'Slot is already booked or does not exist';
  end if;

  select * into v_court from public.courts where id = v_slot.court_id;

  v_dur_min := extract(epoch from (v_slot.end_at - v_slot.start_at))::integer / 60;

  update public.slots set status = 'booked' where id = p_slot_id;

  insert into public.bookings (
    slot_id, user_id, court_id,
    customer_name, customer_phone, notes,
    price_per_hour, duration_minutes, total_price
  ) values (
    p_slot_id,
    p_user_id,
    v_slot.court_id,
    coalesce(p_customer_name,  (select full_name from public.users where id = p_user_id)),
    coalesce(p_customer_phone, (select phone      from public.users where id = p_user_id)),
    p_notes,
    v_court.price_per_hour,
    v_dur_min,
    v_court.price_per_hour * v_dur_min::numeric / 60
  )
  returning * into v_booking;

  return v_booking;
end;
$$;

-- 4.4 Slot expiry & completion — called by pg_cron every 15 minutes (BS-091)
-- Runs entirely in SQL; no external API calls needed.
create or replace function public.expire_slots()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- Mark confirmed bookings as completed when their slot has ended
  update public.bookings b
  set status = 'completed', completed_at = now()
  from public.slots s
  where b.slot_id = s.id
    and b.status = 'confirmed'
    and s.end_at < now();

  -- Re-open slots whose bookings are now completed
  update public.slots s
  set status = 'open'
  from public.bookings b
  where b.slot_id = s.id
    and b.status = 'completed'
    and s.status = 'booked'
    and s.end_at < now();

  -- Auto-cancel pending bookings with no owner response after 24 hours
  update public.bookings
  set status = 'cancelled'
  where status = 'pending'
    and created_at < now() - interval '24 hours';

  -- Re-open slots freed by auto-cancellation
  update public.slots s
  set status = 'open'
  from public.bookings b
  where b.slot_id = s.id
    and b.status = 'cancelled'
    and s.status = 'booked';
end;
$$;

-- 4.5 Mark FCM push reminder candidates — called by pg_cron every 5 minutes (BS-052)
-- Flags bookings due in ~60 min; Django polls and fires the actual FCM push via firebase-admin.
create or replace function public.mark_reminder_candidates()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- No-op: reminder_sent is read by Django's FCM push job.
  -- This function exists so pg_cron has a SQL target to call.
  -- Django query: SELECT * FROM bookings WHERE status = 'confirmed'
  --   AND reminder_sent = false
  --   AND start_at BETWEEN now() + interval '55 min' AND now() + interval '65 min'
  null;
end;
$$;

-- ---------------------------------------------------------------------------
-- 5. Supabase Realtime — enable table publications (BS-040, BS-041, BS-042)
-- ---------------------------------------------------------------------------

alter publication supabase_realtime add table public.slots;
alter publication supabase_realtime add table public.bookings;
alter publication supabase_realtime add table public.notifications;

-- ---------------------------------------------------------------------------
-- 6. pg_cron jobs (BS-090, BS-091, BS-092)
-- Calls pure-SQL PostgreSQL functions — no pg_net / HTTP required.
-- SMS reminders and slot generation are handled by Django (polls DB / cron).
-- ---------------------------------------------------------------------------

-- Slot expiry & completion: every 15 minutes
select cron.schedule(
  'spb-slot-expiry',
  '*/15 * * * *',
  'select public.expire_slots()'
);

-- FCM push reminder marker: every 5 minutes (Django polls; function is a no-op marker)
select cron.schedule(
  'spb-reminder-marker',
  '*/5 * * * *',
  'select public.mark_reminder_candidates()'
);

-- Recurring slot generation: daily at 02:00 ICT (19:00 UTC)
-- Handled by Django management command; no SQL-only equivalent.
-- Register cron in Django scheduler or external cron instead.
