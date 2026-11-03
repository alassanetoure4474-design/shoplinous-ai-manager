-- Persistent Wave Direct payments and signed GeniusPay webhook processing.
-- Store no customer PII. Only the server service role may access these records.

create extension if not exists pgcrypto;

create table if not exists public.shoplinous_orders (
    id uuid primary key default gen_random_uuid(),
    external_order_id text not null unique,
    source text not null default 'freewebstore'
        check (source = 'freewebstore'),
    country text not null check (country ~ '^[A-Z]{2}$'),
    currency text not null check (currency ~ '^[A-Z]{3}$'),
    amount numeric(14, 2) not null check (amount > 0),
    status text not null default 'awaiting_payment'
        check (status in ('awaiting_payment', 'paid', 'cancelled', 'refunded')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.shoplinous_payments (
    id uuid primary key default gen_random_uuid(),
    order_id uuid not null references public.shoplinous_orders(id) on delete restrict,
    provider text not null default 'geniuspay' check (provider = 'geniuspay'),
    method text not null default 'wave' check (method = 'wave'),
    idempotency_key text not null unique
        check (length(idempotency_key) between 8 and 128),
    amount numeric(14, 2) not null check (amount > 0),
    currency text not null check (currency = 'XOF'),
    country text not null check (country = 'CI'),
    environment text not null check (environment = 'sandbox'),
    status text not null default 'creating'
        check (status in ('creating', 'pending', 'succeeded', 'failed',
                          'cancelled', 'expired', 'refunded')),
    provider_reference text unique,
    checkout_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- A single live/pending/succeeded Wave transaction may exist per order.
-- Failed, cancelled and expired attempts can be retried with a new key.
create unique index if not exists shoplinous_one_active_payment_per_order
    on public.shoplinous_payments(order_id)
    where status in ('creating', 'pending', 'succeeded');

create index if not exists shoplinous_payments_order_id_idx
    on public.shoplinous_payments(order_id, created_at desc);

create table if not exists public.geniuspay_webhook_events (
    event_id text primary key,
    delivery_id text,
    payment_id uuid not null references public.shoplinous_payments(id) on delete restrict,
    provider_reference text not null,
    event_type text not null,
    environment text not null check (environment = 'sandbox'),
    provider_status text not null,
    amount numeric(14, 2) not null,
    currency text not null,
    payload_sha256 text not null check (payload_sha256 ~ '^[a-f0-9]{64}$'),
    received_at timestamptz not null default now()
);

-- No browser/client access. All payment state changes go through server-side RPCs.
alter table public.shoplinous_orders enable row level security;
alter table public.shoplinous_payments enable row level security;
alter table public.geniuspay_webhook_events enable row level security;

revoke all on table public.shoplinous_orders from public, anon, authenticated;
revoke all on table public.shoplinous_payments from public, anon, authenticated;
revoke all on table public.geniuspay_webhook_events from public, anon, authenticated;
revoke all on table public.shoplinous_orders from service_role;
revoke all on table public.shoplinous_payments from service_role;
revoke all on table public.geniuspay_webhook_events from service_role;
-- Table access remains closed even to the service role; only the RPCs below may mutate state.

create or replace function public.shoplinous_reserve_wave_payment(
    p_order_number text,
    p_country text,
    p_currency text,
    p_amount numeric,
    p_method text,
    p_idempotency_key text,
    p_environment text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_order public.shoplinous_orders%rowtype;
    v_payment public.shoplinous_payments%rowtype;
    v_created boolean := false;
begin
    if p_order_number is null or length(trim(p_order_number)) = 0
       or length(p_order_number) > 120 then
        raise exception 'invalid_order_number' using errcode = '22023';
    end if;
    if upper(coalesce(p_country, '')) <> 'CI'
       or upper(coalesce(p_currency, '')) <> 'XOF'
       or lower(coalesce(p_method, '')) <> 'wave' then
        raise exception 'wave_requires_ci_xof' using errcode = '22023';
    end if;
    if p_amount is null or p_amount < 200
       or p_amount::text in ('NaN', 'Infinity', '-Infinity')
       or p_amount <> trunc(p_amount) then
        raise exception 'invalid_wave_amount' using errcode = '22023';
    end if;
    if p_idempotency_key is null
       or length(trim(p_idempotency_key)) < 8
       or length(p_idempotency_key) > 128 then
        raise exception 'invalid_idempotency_key' using errcode = '22023';
    end if;
    if lower(coalesce(p_environment, '')) <> 'sandbox' then
        raise exception 'invalid_payment_environment' using errcode = '22023';
    end if;

    insert into public.shoplinous_orders (
        external_order_id, country, currency, amount
    ) values (
        trim(p_order_number), 'CI', 'XOF', p_amount
    )
    on conflict (external_order_id) do nothing;

    select * into v_order
    from public.shoplinous_orders
    where external_order_id = trim(p_order_number)
    for update;

    if v_order.id is null then
        raise exception 'order_reservation_failed' using errcode = 'P0001';
    end if;
    if v_order.country <> 'CI' or v_order.currency <> 'XOF'
       or v_order.amount <> p_amount then
        raise exception 'order_amount_or_destination_mismatch' using errcode = '23514';
    end if;
    if v_order.status <> 'awaiting_payment' then
        raise exception 'order_not_payable' using errcode = '23514';
    end if;

    select * into v_payment
    from public.shoplinous_payments
    where idempotency_key = p_idempotency_key
    for update;

    if v_payment.id is not null then
        if v_payment.order_id <> v_order.id
           or v_payment.amount <> p_amount
           or v_payment.currency <> 'XOF'
           or v_payment.country <> 'CI'
           or v_payment.method <> 'wave'
           or v_payment.environment <> lower(p_environment) then
            raise exception 'idempotency_key_reused_for_different_payment'
                using errcode = '23505';
        end if;
        return jsonb_build_object(
            'created', false,
            'payment_id', v_payment.id,
            'order_number', trim(p_order_number),
            'status', v_payment.status,
            'provider_reference', v_payment.provider_reference,
            'checkout_url', v_payment.checkout_url,
            'environment', v_payment.environment
        );
    end if;

    if exists (
        select 1
        from public.shoplinous_payments
        where order_id = v_order.id
          and status in ('creating', 'pending', 'succeeded')
    ) then
        -- A different key must not silently alias an existing checkout.
        -- Reuse the original idempotency key or reconcile the attempt first.
        raise exception 'payment_already_reserved_use_same_idempotency_key'
            using errcode = '23505';
    end if;

    insert into public.shoplinous_payments (
        order_id, idempotency_key, amount, currency, country,
        method, provider, environment, status
    ) values (
        v_order.id, p_idempotency_key, p_amount, 'XOF', 'CI',
        'wave', 'geniuspay', lower(p_environment), 'creating'
    )
    returning * into v_payment;
    v_created := true;

    return jsonb_build_object(
        'created', v_created,
        'payment_id', v_payment.id,
        'order_number', trim(p_order_number),
        'status', v_payment.status,
        'provider_reference', v_payment.provider_reference,
        'checkout_url', v_payment.checkout_url,
        'environment', v_payment.environment
    );
end;
$$;

create or replace function public.shoplinous_finalize_wave_checkout(
    p_payment_id uuid,
    p_reference text,
    p_checkout_url text,
    p_environment text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_payment public.shoplinous_payments%rowtype;
begin
    if p_payment_id is null
       or p_reference is null
       or length(trim(p_reference)) = 0
       or length(p_reference) > 120 then
        raise exception 'invalid_checkout_reference' using errcode = '22023';
    end if;
    if p_checkout_url is null
       or p_checkout_url !~ '^https://(www\.)?wave\.com/' then
        raise exception 'invalid_wave_checkout_url' using errcode = '22023';
    end if;
    if lower(coalesce(p_environment, '')) <> 'sandbox' then
        raise exception 'invalid_payment_environment' using errcode = '22023';
    end if;

    select * into v_payment
    from public.shoplinous_payments
    where id = p_payment_id
    for update;

    if v_payment.id is null then
        raise exception 'payment_not_found' using errcode = 'P0002';
    end if;
    if v_payment.environment <> lower(p_environment) then
        raise exception 'payment_environment_mismatch' using errcode = '23514';
    end if;

    if v_payment.status = 'pending'
       and v_payment.provider_reference = trim(p_reference)
       and v_payment.checkout_url = p_checkout_url then
        return jsonb_build_object(
            'created', false, 'payment_id', v_payment.id,
            'status', v_payment.status,
            'provider_reference', v_payment.provider_reference,
            'checkout_url', v_payment.checkout_url,
            'environment', v_payment.environment
        );
    end if;

    if v_payment.status <> 'creating'
       or v_payment.provider_reference is not null
       or v_payment.checkout_url is not null then
        raise exception 'payment_checkout_already_finalized_or_not_creating'
            using errcode = '23505';
    end if;

    update public.shoplinous_payments
    set provider_reference = trim(p_reference),
        checkout_url = p_checkout_url,
        status = 'pending',
        updated_at = now()
    where id = p_payment_id
    returning * into v_payment;

    return jsonb_build_object(
        'created', true, 'payment_id', v_payment.id,
        'status', v_payment.status,
        'provider_reference', v_payment.provider_reference,
        'checkout_url', v_payment.checkout_url,
        'environment', v_payment.environment
    );
end;
$$;

create or replace function public.shoplinous_process_geniuspay_webhook(
    p_event_id text,
    p_delivery_id text,
    p_reference text,
    p_event_type text,
    p_environment text,
    p_amount numeric,
    p_currency text,
    p_order_number text,
    p_provider_status text,
    p_payload_sha256 text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_payment public.shoplinous_payments%rowtype;
    v_order public.shoplinous_orders%rowtype;
    v_inserted integer := 0;
    v_existing_hash text;
    v_new_status text;
begin
    if p_event_id is null or length(trim(p_event_id)) = 0
       or length(p_event_id) > 160
       or p_reference is null or length(trim(p_reference)) = 0
       or length(p_reference) > 120
       or p_order_number is null or length(trim(p_order_number)) = 0 then
        raise exception 'invalid_webhook_identifiers' using errcode = '22023';
    end if;
    if lower(coalesce(p_environment, '')) not in ('sandbox', 'live')
       or upper(coalesce(p_currency, '')) <> 'XOF'
       or p_amount is null or p_amount < 200
       or p_amount::text in ('NaN', 'Infinity', '-Infinity')
       or p_amount <> trunc(p_amount) then
        raise exception 'invalid_webhook_payment_fields' using errcode = '22023';
    end if;
    if p_payload_sha256 is null
       or p_payload_sha256 !~ '^[a-f0-9]{64}$' then
        raise exception 'invalid_webhook_payload_hash' using errcode = '22023';
    end if;

    select * into v_payment
    from public.shoplinous_payments
    where provider = 'geniuspay'
      and provider_reference = trim(p_reference)
    for update;

    if v_payment.id is null then
        raise exception 'payment_reference_not_found' using errcode = 'P0002';
    end if;

    select * into v_order
    from public.shoplinous_orders
    where id = v_payment.order_id
    for update;

    if v_order.id is null
       or v_order.external_order_id <> trim(p_order_number)
       or v_payment.amount <> p_amount
       or v_payment.currency <> upper(p_currency)
       or v_payment.environment <> lower(p_environment) then
        raise exception 'webhook_payment_mismatch' using errcode = '23514';
    end if;

    if p_event_type = 'payment.success' then
        if lower(coalesce(p_provider_status, '')) <> 'completed' then
            raise exception 'success_event_not_completed' using errcode = '23514';
        end if;
        v_new_status := 'succeeded';
    elsif p_event_type = 'payment.failed' then
        if lower(coalesce(p_provider_status, '')) <> 'failed' then
            raise exception 'failed_event_status_mismatch' using errcode = '23514';
        end if;
        v_new_status := 'failed';
    elsif p_event_type = 'payment.cancelled' then
        if lower(coalesce(p_provider_status, '')) not in ('cancelled', 'canceled') then
            raise exception 'cancelled_event_status_mismatch' using errcode = '23514';
        end if;
        v_new_status := 'cancelled';
    elsif p_event_type = 'payment.expired' then
        if lower(coalesce(p_provider_status, '')) <> 'expired' then
            raise exception 'expired_event_status_mismatch' using errcode = '23514';
        end if;
        v_new_status := 'expired';
    elsif p_event_type = 'payment.refunded' then
        if lower(coalesce(p_provider_status, '')) <> 'refunded' then
            raise exception 'refunded_event_status_mismatch' using errcode = '23514';
        end if;
        v_new_status := 'refunded';
    else
        raise exception 'unsupported_geniuspay_event' using errcode = '22023';
    end if;

    insert into public.geniuspay_webhook_events (
        event_id, delivery_id, payment_id, provider_reference,
        event_type, environment, provider_status, amount, currency,
        payload_sha256
    ) values (
        trim(p_event_id), nullif(trim(coalesce(p_delivery_id, '')), ''),
        v_payment.id, trim(p_reference), p_event_type,
        lower(p_environment), lower(p_provider_status), p_amount,
        upper(p_currency), p_payload_sha256
    )
    on conflict (event_id) do nothing;

    get diagnostics v_inserted = row_count;
    if v_inserted = 0 then
        select payload_sha256 into v_existing_hash
        from public.geniuspay_webhook_events
        where event_id = trim(p_event_id);
        if v_existing_hash is distinct from p_payload_sha256 then
            raise exception 'webhook_event_id_reused_with_different_payload'
                using errcode = '23505';
        end if;
        return jsonb_build_object(
            'duplicate', true, 'payment_id', v_payment.id,
            'payment_status', v_payment.status,
            'order_status', v_order.status
        );
    end if;

    if v_new_status = 'succeeded' then
        if v_payment.status not in ('creating', 'pending', 'succeeded') then
            raise exception 'late_success_requires_manual_reconciliation'
                using errcode = '23514';
        end if;
        update public.shoplinous_payments
        set status = 'succeeded', updated_at = now()
        where id = v_payment.id;
        if v_order.status = 'awaiting_payment' then
            update public.shoplinous_orders
            set status = 'paid', updated_at = now()
            where id = v_order.id;
            v_order.status := 'paid';
        elsif v_order.status <> 'paid' then
            raise exception 'order_not_eligible_for_paid_status'
                using errcode = '23514';
        end if;
        v_payment.status := 'succeeded';
    elsif v_new_status = 'refunded' then
        if v_payment.status not in ('succeeded', 'refunded')
           or v_order.status not in ('paid', 'refunded') then
            raise exception 'refund_without_successful_payment'
                using errcode = '23514';
        end if;
        update public.shoplinous_payments
        set status = 'refunded', updated_at = now()
        where id = v_payment.id;
        update public.shoplinous_orders
        set status = 'refunded', updated_at = now()
        where id = v_order.id;
        v_payment.status := 'refunded';
        v_order.status := 'refunded';
    else
        -- Never downgrade a successful/refunded payment on a later stale event.
        if v_payment.status in ('creating', 'pending') then
            update public.shoplinous_payments
            set status = v_new_status, updated_at = now()
            where id = v_payment.id;
            v_payment.status := v_new_status;
        end if;
    end if;

    return jsonb_build_object(
        'duplicate', false, 'payment_id', v_payment.id,
        'payment_status', v_payment.status,
        'order_status', v_order.status
    );
end;
$$;

revoke all on function public.shoplinous_reserve_wave_payment(
    text, text, text, numeric, text, text, text
) from public, anon, authenticated;
revoke all on function public.shoplinous_finalize_wave_checkout(
    uuid, text, text, text
) from public, anon, authenticated;
revoke all on function public.shoplinous_process_geniuspay_webhook(
    text, text, text, text, text, numeric, text, text, text, text
) from public, anon, authenticated;

grant execute on function public.shoplinous_reserve_wave_payment(
    text, text, text, numeric, text, text, text
) to service_role;
grant execute on function public.shoplinous_finalize_wave_checkout(
    uuid, text, text, text
) to service_role;
grant execute on function public.shoplinous_process_geniuspay_webhook(
    text, text, text, text, text, numeric, text, text, text, text
) to service_role;
