-- Public storefront catalogue: one listing per product and destination market.
-- Anonymous visitors can only read explicitly qualified, recently verified listings.
create extension if not exists pgcrypto;

create table if not exists public.storefront_products (
  id uuid primary key default gen_random_uuid(),
  slug text not null check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  market_code text not null check (market_code ~ '^[A-Z]{2}$'),
  name text not null check (length(trim(name)) between 2 and 180),
  short_description text not null default '' check (length(short_description) <= 280),
  description text not null default '',
  category_slug text not null,
  price numeric(14,2) not null check (price > 0),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  image_urls text[] not null check (cardinality(image_urls) >= 2),
  is_published boolean not null default false,
  is_qualified boolean not null default false,
  is_active boolean not null default true,
  supplier_verified_at timestamptz,
  compliance_verified_at timestamptz,
  images_verified_at timestamptz,
  stock_verified_at timestamptz,
  shipping_verified_at timestamptz,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (slug, market_code)
);

create index if not exists storefront_products_public_idx
  on public.storefront_products(market_code, category_slug, published_at desc)
  where is_published and is_qualified and is_active;

alter table public.storefront_products enable row level security;
revoke all on table public.storefront_products from public, anon, authenticated;
grant select (
  id, slug, market_code, name, short_description, description,
  category_slug, price, currency, image_urls, published_at
) on public.storefront_products to anon, authenticated;
grant all on public.storefront_products to service_role;

drop policy if exists "Public can read verified storefront products" on public.storefront_products;
create policy "Public can read verified storefront products"
on public.storefront_products for select
to anon, authenticated
using (
  is_published = true
  and is_qualified = true
  and is_active = true
  and price > 0
  and cardinality(image_urls) >= 2
  and supplier_verified_at > now() - interval '30 days'
  and compliance_verified_at is not null
  and images_verified_at > now() - interval '7 days'
  and stock_verified_at > now() - interval '1 hour'
  and shipping_verified_at > now() - interval '1 hour'
  and published_at is not null
);

comment on table public.storefront_products is
  'Public projection: one country-specific listing per product. Only the server can publish after full supplier, compliance, stock, shipping and margin qualification.';
