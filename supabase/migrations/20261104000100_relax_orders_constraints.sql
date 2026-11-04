-- Relaxation des contraintes de shoplinous_orders : la boutique vend
-- desormais en EUR (marche europeen) en plus de XOF (CI).

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
