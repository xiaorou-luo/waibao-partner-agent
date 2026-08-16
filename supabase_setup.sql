-- 外脑伙伴 · Supabase 建表脚本
-- 用法：Supabase 后台 → SQL Editor → New query → 粘贴全部内容 → Run

create table if not exists public.user_data (
  user_id uuid primary key references auth.users(id) on delete cascade,
  files jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.user_data enable row level security;

drop policy if exists "own user data" on public.user_data;
create policy "own user data"
  on public.user_data
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
