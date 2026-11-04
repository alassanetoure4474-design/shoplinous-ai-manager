-- Corrige la validation d'URL de checkout : le domaine apex
-- https://geniuspay.ci/... (sans sous-domaine) etait rejete par la regex
-- '([a-z0-9-]+[.])+' ce qui faisait echouer toute finalisation
-- (invalid_checkout_url -> 503 checkout_finalization_failed -> paiements
-- bloques en statut 'creating' -> webhooks rejetes).
-- Sous-domaine desormais optionnel ; seuls geniuspay.ci et wave.com restent
-- autorises, en HTTPS, avec un chemin/query obligatoire.

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
       or p_checkout_url !~ '^https://([a-z0-9-]+[.])*(geniuspay[.]ci|wave[.]com)(/|[$]|[?])' then
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

revoke all on function public.shoplinous_finalize_checkout(
    uuid, text, text, text
) from public, anon, authenticated;
grant execute on function public.shoplinous_finalize_checkout(
    uuid, text, text, text
) to service_role;
