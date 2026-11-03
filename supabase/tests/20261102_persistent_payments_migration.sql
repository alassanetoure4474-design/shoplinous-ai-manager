-- Executed against an ephemeral PostgreSQL instance in CI.
-- The workflow creates Supabase-compatible roles before applying the migration.
DO $$
BEGIN
    IF NOT (SELECT relrowsecurity FROM pg_class
            WHERE oid = 'public.shoplinous_orders'::regclass) THEN
        RAISE EXCEPTION 'RLS is not enabled on shoplinous_orders';
    END IF;
    IF NOT (SELECT relrowsecurity FROM pg_class
            WHERE oid = 'public.shoplinous_payments'::regclass) THEN
        RAISE EXCEPTION 'RLS is not enabled on shoplinous_payments';
    END IF;
    IF NOT (SELECT relrowsecurity FROM pg_class
            WHERE oid = 'public.geniuspay_webhook_events'::regclass) THEN
        RAISE EXCEPTION 'RLS is not enabled on geniuspay_webhook_events';
    END IF;

    IF has_table_privilege('anon', 'public.shoplinous_orders', 'SELECT')
       OR has_table_privilege('authenticated', 'public.shoplinous_orders', 'SELECT')
       OR has_table_privilege('service_role', 'public.shoplinous_orders', 'SELECT')
       OR has_table_privilege('service_role', 'public.shoplinous_payments', 'INSERT')
       OR has_table_privilege('service_role', 'public.geniuspay_webhook_events', 'UPDATE') THEN
        RAISE EXCEPTION 'A role has forbidden direct table privileges';
    END IF;

    IF has_function_privilege(
        'anon',
        'public.shoplinous_reserve_wave_payment(text,text,text,numeric,text,text,text)',
        'EXECUTE'
    ) OR has_function_privilege(
        'authenticated',
        'public.shoplinous_process_geniuspay_webhook(text,text,text,text,text,numeric,text,text,text,text)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'A client role can execute a privileged payment RPC';
    END IF;

    IF NOT has_function_privilege(
        'service_role',
        'public.shoplinous_reserve_wave_payment(text,text,text,numeric,text,text,text)',
        'EXECUTE'
    ) OR NOT has_function_privilege(
        'service_role',
        'public.shoplinous_finalize_wave_checkout(uuid,text,text,text)',
        'EXECUTE'
    ) OR NOT has_function_privilege(
        'service_role',
        'public.shoplinous_process_geniuspay_webhook(text,text,text,text,text,numeric,text,text,text,text)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'service_role is missing an expected payment RPC grant';
    END IF;
END;
$$;

-- Execute the security-definer RPCs as the same restricted role used by the
-- backend. This verifies the database access path, not just function metadata.
SET ROLE service_role;
DO $$
DECLARE
    v_reserved jsonb;
    v_checkout jsonb;
    v_webhook jsonb;
    v_duplicate jsonb;
    v_payment_id uuid;
    v_event_hash text := repeat('a', 64);
BEGIN
    v_reserved := public.shoplinous_reserve_wave_payment(
        'FW-MIGRATION-CHECK-001',
        'CI',
        'XOF',
        2500,
        'wave',
        'migration-check-idem-001',
        'sandbox'
    );

    IF v_reserved->>'created' <> 'true'
       OR v_reserved->>'status' <> 'creating' THEN
        RAISE EXCEPTION 'Payment reservation returned an unexpected state: %', v_reserved;
    END IF;
    v_payment_id := (v_reserved->>'payment_id')::uuid;

    v_checkout := public.shoplinous_finalize_wave_checkout(
        v_payment_id,
        'GP-MIGRATION-CHECK-001',
        'https://wave.com/checkout/GP-MIGRATION-CHECK-001',
        'sandbox'
    );
    IF v_checkout->>'status' <> 'pending'
       OR v_checkout->>'provider_reference' <> 'GP-MIGRATION-CHECK-001' THEN
        RAISE EXCEPTION 'Checkout finalization returned an unexpected state: %', v_checkout;
    END IF;

    v_webhook := public.shoplinous_process_geniuspay_webhook(
        'evt-migration-check-001',
        'delivery-migration-check-001',
        'GP-MIGRATION-CHECK-001',
        'payment.success',
        'sandbox',
        2500,
        'XOF',
        'FW-MIGRATION-CHECK-001',
        'completed',
        v_event_hash
    );
    IF v_webhook->>'duplicate' <> 'false'
       OR v_webhook->>'payment_status' <> 'succeeded'
       OR v_webhook->>'order_status' <> 'paid' THEN
        RAISE EXCEPTION 'Successful webhook did not atomically mark order paid: %', v_webhook;
    END IF;

    v_duplicate := public.shoplinous_process_geniuspay_webhook(
        'evt-migration-check-001',
        'delivery-migration-check-001',
        'GP-MIGRATION-CHECK-001',
        'payment.success',
        'sandbox',
        2500,
        'XOF',
        'FW-MIGRATION-CHECK-001',
        'completed',
        v_event_hash
    );
    IF v_duplicate->>'duplicate' <> 'true' THEN
        RAISE EXCEPTION 'Repeated webhook event was not idempotent: %', v_duplicate;
    END IF;

    -- A webhook with an incorrect amount must be rejected.
    BEGIN
        PERFORM public.shoplinous_process_geniuspay_webhook(
            'evt-migration-check-wrong-amount',
            NULL,
            'GP-MIGRATION-CHECK-001',
            'payment.success',
            'sandbox',
            2501,
            'XOF',
            'FW-MIGRATION-CHECK-001',
            'completed',
            repeat('b', 64)
        );
        RAISE EXCEPTION 'A webhook with an incorrect amount was accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    -- The database itself must reject Live, even if a caller reaches the RPC.
    BEGIN
        PERFORM public.shoplinous_reserve_wave_payment(
            'FW-MIGRATION-CHECK-LIVE',
            'CI',
            'XOF',
            2500,
            'wave',
            'migration-check-idem-live',
            'live'
        );
        RAISE EXCEPTION 'Live payment reservation was accepted';
    EXCEPTION
        WHEN invalid_parameter_value THEN
            NULL;
    END;

    -- The webhook RPC must independently reject Live as defense in depth.
    BEGIN
        PERFORM public.shoplinous_process_geniuspay_webhook(
            'evt-migration-check-live',
            NULL,
            'GP-MIGRATION-CHECK-001',
            'payment.success',
            'live',
            2500,
            'XOF',
            'FW-MIGRATION-CHECK-001',
            'completed',
            repeat('c', 64)
        );
        RAISE EXCEPTION 'Live webhook was accepted by the database';
    EXCEPTION
        WHEN invalid_parameter_value THEN
            NULL;
    END;
END;
$$;
RESET ROLE;
