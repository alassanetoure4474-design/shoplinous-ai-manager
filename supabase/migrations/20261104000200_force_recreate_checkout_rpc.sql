-- Reconstruction idempotente du schema checkout : les RPC du
-- 20261104000000 n'existaient pas en base (historique faux). Ce script
-- re-applique contraintes + fonctions de facon re-executable.

-- 1. Contraintes shoplinous_payments (drop-all puis re-add).
do $$
declare
    r record;
begin
    for r in
        select conname
        from pg_constraint
        where conrelid = 'public.shoplinous_payments'::regclass
          and contype = 'c'
    loop
        execute 'alter table public.shoplinous_payments drop constraint '
            || quote_ident(r.conname);
    end loop;
end $$;

alter table public.shoplinous_payments
    add constraint shoplinous_payments_provider_check
        check (provider = 'geniuspay'),
    add constraint shoplinous_payments_method_check
        check (method in ('wave', 'card')),
    add constraint shoplinous_payments_currency_check
        check (currency in ('XOF', 'EUR')),
    add constraint shoplinous_payments_country_check
        check (country ~ '^[A-Z]{2}$'),
    add constraint shoplinous_payments_environment_check
        check (environment = 'sandbox'),
    add constraint shoplinous_payments_status_check
        check (status in ('creating', 'pending', 'succeeded', 'failed',
                          'cancelled', 'expired', 'refunded')),
    add constraint shoplinous_payments_idempotency_key_check
        check (length(idempotency_key) between 8 and 128);

-- 2. Contraintes shoplinous_orders (EUR accepte).
do $$
declare
    r record;
begin
    for r in
        select conname
        from pg_constraint
        where conrelid = 'public.shoplinous_orders'::regclass
          and contype = 'c'
    loop
        execute 'alter table public.shoplinous_orders drop constraint '
            || quote_ident(r.conname);
    end loop;
end $$;

alter table public.shoplinous_orders
    add constraint shoplinous_orders_currency_check
        check (currency in ('XOF', 'EUR')),
    add constraint shoplinous_orders_country_check
        check (country ~ '^[A-Z]{2}$'),
    add constraint shoplinous_orders_amount_check
        check (amount > 0);

-- 3. Fonctions RPC du checkout (create or replace).
-- 2. Reservation generique : EUR/carte (marche europeen) ou XOF/wave (CI).
--    Montant COMMANDE = unites majeures (24.90 EUR, 200 XOF) ; montant
--    PAIEMENT stocke = unite API GeniusPay (centimes EUR, unites XOF).
create or replace function public.shoplinous_reserve_payment(
    p_order_number text,
    p_country text,
    p_currency text,
    p_order_amount numeric,
    p_method text,
    p_idempotency_key text,
    p_environment text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
    v_order public.shoplinous_orders%rowtype;
    v_payment public.shoplinous_payments%rowtype;
    v_currency text;
    v_method text;
    v_country text;
    v_api_amount numeric;
    v_created boolean := false;
begin
    if p_order_number is null or length(trim(p_order_number)) = 0
       or length(p_order_number) > 120 then
        raise exception 'invalid_order_number' using errcode = '22023';
    end if;
    v_currency := upper(coalesce(p_currency, ''));
    v_method := lower(coalesce(p_method, ''));
    v_country := upper(coalesce(p_country, ''));
    if v_currency = 'EUR' then
        if v_method <> 'card' then
            raise exception 'eur_requires_card_method' using errcode = '22023';
        end if;
        if v_country !~ '^[A-Z]{2}$' then
            raise exception 'invalid_country' using errcode = '22023';
        end if;
        if p_order_amount is null
           or p_order_amount < 2.00
           or p_order_amount > 1000000
           or p_order_amount <> round(p_order_amount, 2) then
            raise exception 'invalid_eur_order_amount' using errcode = '22023';
        end if;
        v_api_amount := round(p_order_amount * 100);
    elsif v_currency = 'XOF' then
        if v_method <> 'wave' or v_country <> 'CI' then
            raise exception 'wave_requires_ci_xof' using errcode = '22023';
        end if;
        if p_order_amount is null
           or p_order_amount < 200
           or p_order_amount <> trunc(p_order_amount) then
            raise exception 'invalid_wave_amount' using errcode = '22023';
        end if;
        v_api_amount := p_order_amount;
    else
        raise exception 'unsupported_payment_currency' using errcode = '22023';
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
        trim(p_order_number), v_country, v_currency, p_order_amount
    )
    on conflict (external_order_id) do nothing;

    select * into v_order
    from public.shoplinous_orders
    where external_order_id = trim(p_order_number)
    for update;

    if v_order.id is null then
        raise exception 'order_reservation_failed' using errcode = 'P0001';
    end if;
    if v_order.country <> v_country
       or v_order.currency <> v_currency
       or v_order.amount <> p_order_amount then
        raise exception 'order_amount_or_destination_mismatch'
            using errcode = '23514';
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
           or v_payment.amount <> v_api_amount
           or v_payment.currency <> v_currency
           or v_payment.country <> v_country
           or v_payment.method <> v_method
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
        raise exception 'payment_already_reserved_use_same_idempotency_key'
            using errcode = '23505';
    end if;

    insert into public.shoplinous_payments (
        order_id, idempotency_key, amount, currency, country,
        method, provider, environment, status
    ) values (
        v_order.id, p_idempotency_key, v_api_amount, v_currency, v_country,
        v_method, 'geniuspay', lower(p_environment), 'creating'
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

-- 3. Finalisation generique du checkout : l'URL hebergee doit appartenir
--    aux domaines GeniusPay ou Wave (jamais un domaine arbitraire).
create or replace function public.shoplinous_finalize_checkout(
    p_payment_id uuid,
    p_reference text,
    p_checkout_url text,
    p_environment text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
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
       or p_checkout_url !~ '^https://([a-z0-9-]+[.])+(geniuspay[.]ci|wave[.]com)(/|[$]|[?])' then
        raise exception 'invalid_checkout_url' using errcode = '22023';
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

-- 4. Statut de commande/paiement (lecture, sans donnee personnelle).
create or replace function public.shoplinous_order_status(
    p_order_number text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
    v_order public.shoplinous_orders%rowtype;
    v_payment public.shoplinous_payments%rowtype;
    v_attempts integer := 0;
begin
    if p_order_number is null or length(trim(p_order_number)) = 0 then
        raise exception 'invalid_order_number' using errcode = '22023';
    end if;
    select * into v_order
    from public.shoplinous_orders
    where external_order_id = trim(p_order_number);
    if v_order.id is null then
        raise exception 'order_not_found' using errcode = 'P0002';
    end if;
    select count(*) into v_attempts
    from public.shoplinous_payments
    where order_id = v_order.id;
    select * into v_payment
    from public.shoplinous_payments
    where order_id = v_order.id
    order by created_at desc
    limit 1;
    return jsonb_build_object(
        'order_number', v_order.external_order_id,
        'order_status', v_order.status,
        'payment_status', v_payment.status,
        'payment_method', v_payment.method,
        'amount_api', v_payment.amount,
        'currency', v_payment.currency,
        'attempts', v_attempts,
        'environment', v_payment.environment
    );
end;
$$;

-- 5. Webhook generique : XOF (unites entieres) ou EUR (centimes entiers).
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
set search_path = pg_catalog, public, pg_temp
as $$
declare
    v_payment public.shoplinous_payments%rowtype;
    v_order public.shoplinous_orders%rowtype;
    v_inserted integer := 0;
    v_existing_hash text;
    v_new_status text;
    v_currency text;
begin
    if p_event_id is null or length(trim(p_event_id)) = 0
       or length(p_event_id) > 160
       or p_reference is null or length(trim(p_reference)) = 0
       or length(p_reference) > 120
       or p_order_number is null or length(trim(p_order_number)) = 0 then
        raise exception 'invalid_webhook_identifiers' using errcode = '22023';
    end if;
    v_currency := upper(coalesce(p_currency, ''));
    if lower(coalesce(p_environment, '')) <> 'sandbox' then
        raise exception 'invalid_webhook_environment' using errcode = '22023';
    end if;
    if p_amount is null or p_amount <= 0
       or p_amount::text in ('NaN', 'Infinity', '-Infinity')
       or p_amount <> trunc(p_amount) then
        raise exception 'invalid_webhook_amount' using errcode = '22023';
    end if;
    if v_currency = 'XOF' then
        if p_amount < 200 then
            raise exception 'invalid_webhook_amount' using errcode = '22023';
        end if;
    elsif v_currency = 'EUR' then
        if p_amount < 200 or p_amount > 100000000 then
            raise exception 'invalid_webhook_amount' using errcode = '22023';
        end if;
    else
        raise exception 'invalid_webhook_currency' using errcode = '22023';
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
       or v_payment.currency <> v_currency
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
        v_currency, p_payload_sha256
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

revoke all on function public.shoplinous_reserve_payment(
    text, text, text, numeric, text, text, text
) from public, anon, authenticated;
revoke all on function public.shoplinous_finalize_checkout(
    uuid, text, text, text
) from public, anon, authenticated;
revoke all on function public.shoplinous_order_status(
    text
) from public, anon, authenticated;
revoke all on function public.shoplinous_process_geniuspay_webhook(
    text, text, text, text, text, numeric, text, text, text, text
) from public, anon, authenticated;

grant execute on function public.shoplinous_reserve_payment(
    text, text, text, numeric, text, text, text
) to service_role;
grant execute on function public.shoplinous_finalize_checkout(
    uuid, text, text, text
) to service_role;
grant execute on function public.shoplinous_order_status(
    text
) to service_role;
grant execute on function public.shoplinous_process_geniuspay_webhook(
    text, text, text, text, text, numeric, text, text, text, text
) to service_role;
