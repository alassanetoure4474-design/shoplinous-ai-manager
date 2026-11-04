-- Ajout du moyen de paiement "mobile_money" pour CI/XOF : checkout
-- heberge GeniusPay ou le client choisit Wave, Orange Money ou MTN MoMo.
-- Migration additive et reversible (contrainte + validation reserve).

alter table public.shoplinous_payments
    drop constraint shoplinous_payments_method_check;
alter table public.shoplinous_payments
    add constraint shoplinous_payments_method_check
        check (method in ('wave', 'card', 'mobile_money'));

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
        if v_method not in ('wave', 'mobile_money') or v_country <> 'CI' then
            raise exception 'wave_or_mobile_money_requires_ci_xof'
                using errcode = '22023';
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

revoke all on function public.shoplinous_reserve_payment(
    text, text, text, numeric, text, text, text
) from public, anon, authenticated;
grant execute on function public.shoplinous_reserve_payment(
    text, text, text, numeric, text, text, text
) to service_role;
