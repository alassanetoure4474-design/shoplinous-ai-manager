
create table if not exists public.products (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  supplier text,
  supplier_url text,
  purchase_price numeric(12,2) not null default 0
    check (purchase_price >= 0),
  sale_price numeric(12,2) not null default 0
    check (sale_price >= 0),
  stock integer not null default 0
    check (stock >= 0),
  status text not null default 'Disponible'
    check (status in ('Disponible', 'En commande', 'Épuisé')),
  created_at timestamptz not null default now()
);

alter table public.products enable row level security;

create policy "Users can view their products"
on public.products for select
to authenticated
using ((select auth.uid()) = user_id);

create policy "Users can add their products"
on public.products for insert
to authenticated
with check ((select auth.uid()) = user_id);

create policy "Users can update their products"
on public.products for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy "Users can delete their products"
on public.products for delete
to authenticated
using ((select auth.uid()) = user_id);
