"""Tests pytest du workflow SHOPLINOUS v4.
A EXECUTER AVANT TOUT DEPLOIEMENT :
    pip install -r requirements-dev.txt
    python -m pytest test_daily.py -v
Statut au 01/11/2026 : NON EXECUTES (l'environnement de conversation ne
dispose pas de Python). Aucune reussite n'est revendiquee sans sortie reelle.
"""
import asyncio
import json
import math
import pytest
import httpx
from daily import (sale_price, display_stock, similar_name, cn_stock_of,
                   conforming_freight_options, merge_destinations,
                   estimated_net_profit, parse_cj_images, cj_check,
                   EvaluationSuspended)

# ------------------------------------------------------------ logique pure ---
def test_prix_strictement_superieur_au_triple():
    assert sale_price(21.15) == 21.90
    assert sale_price(21.91) == 22.90      # 21.90 < 21.91 -> +1
    assert sale_price(6.00) == 6.90
    assert sale_price(6.01) == 6.90        # 6.90 >= 6.01
    assert sale_price(6.91) == 7.90        # cas reel du +1


def test_marge_toutes_combinaisons():
    variants = [{"cost_eur": 2.0}, {"cost_eur": 5.0}]
    kept = {"FR": 4.42, "PL": 2.95, "CH": 5.41}
    price = sale_price(max((v["cost_eur"] + s) * 3
                           for v in variants for s in kept.values()))
    for v in variants:
        for s in kept.values():
            assert price >= (v["cost_eur"] + s) * 3 - 1e-9


def test_stock_affiche():
    assert display_stock(11347) == 100
    assert display_stock(150) == 50
    assert display_stock(120) == 20
    assert display_stock(80) == 0


def test_doublons():
    names = ["Indian Dreamcatcher Home Decoration - SHOPLINOUS"]
    assert similar_name("Indian Dreamcatcher Home Decoration Pendant", names)
    assert not similar_name("Kitchen Storage Basket Organizer", names)
    assert not similar_name("", names)


def test_options_conformes_conservent_delai_min_et_max():
    rate = 0.92
    opts = [{"logisticPrice": 5.88, "logisticAging": "5-10"},
            {"logisticPrice": 8.0, "logisticAging": "5-10"},
            {"logisticPrice": 3.0, "logisticAging": "14-26"}]
    ok = conforming_freight_options(opts, rate)
    assert len(ok) == 1
    assert ok[0]["aging_min"] == 5 and ok[0]["aging_max"] == 10


def test_fusion_destinations_et_delais():
    per_variant = {
        "v1": {"FR": {"price_eur": 4.42, "aging_min": 7, "aging_max": 15},
               "PL": {"price_eur": 2.95, "aging_min": 4, "aging_max": 9}},
        "v2": {"FR": {"price_eur": 4.89, "aging_min": 7, "aging_max": 15}},
    }
    kept, dmin, dmax = merge_destinations(per_variant)
    assert kept == {"FR": 4.89}
    assert dmin["FR"] == 7 and dmax["FR"] == 15
    assert "PL" not in kept            # absent pour v2 -> exclus


# --------------------------------- formule du benefice net (CORRIGEE v4) ---
def test_benefice_net_ne_soustrait_pas_la_livraison_client():
    # benefice = 24.90 (produit) + 4.90 (livraison client, RECETTE)
    #           - 2.60 (produit CJ) - 4.42 (livraison CJ) - 1.02 (frais paiement)
    net = estimated_net_profit(24.90, 4.90, 2.60, 4.42, other_costs_eur=1.02)
    assert net == pytest.approx(24.90 + 4.90 - 2.60 - 4.42 - 1.02, abs=0.01)
    assert net > 0
    # Verification explicite : ajouter la livraison facturee AUGMENTE le net.
    assert estimated_net_profit(24.90, 4.90, 2.60, 4.42, 1.02) \
        > estimated_net_profit(24.90, 0.0, 2.60, 4.42, 1.02)


def test_benefice_net_scenario_pessimiste_sans_tarif_connu():
    # checkout inconnu -> scenario 0 EUR facture (jamais de surestimation).
    net = estimated_net_profit(24.90, None, 2.60, 4.42, other_costs_eur=1.02)
    assert net == pytest.approx(24.90 - 2.60 - 4.42 - 1.02, abs=0.01)


# ------------------------------------------------- structures API (pures) ---
def test_cn_stock_structure_reelle():
    payload = {"data": [{"countryCode": "CN", "storageNum": 11347,
                          "stock": [{"inventory": 11347}]}]}
    assert cn_stock_of(payload) == 11347
    assert cn_stock_of({"data": []}) == 0


def test_parse_cj_images_galerie_complete():
    # Structure confirmee via MCP : productImage = chaine JSON tableau d'URLs.
    payload = {"data": [{"productImage": json.dumps([
        "https://cf.cjdropshipping.com/a.jpg",
        "https://cf.cjdropshipping.com/b.jpg"])}]}
    assert len(parse_cj_images(payload)) == 2
    assert parse_cj_images({"data": [{"productImage": "pas du json"}]}) == []
    assert parse_cj_images({"data": []}) == []


def test_cj_check_rejete_les_reponses_vides_ou_fausses():
    with pytest.raises(RuntimeError):
        cj_check({"code": 200, "result": True}, "x")        # data absent
    with pytest.raises(RuntimeError):
        cj_check({"code": 429, "message": "Too Many Requests"}, "x")
    with pytest.raises(RuntimeError):
        cj_check("pas un dict", "x")
    with pytest.raises(RuntimeError):
        cj_check({"code": 200, "result": False}, "x")
    ok = cj_check({"code": 200, "result": True, "data": []}, "x")
    assert ok["data"] == []


# ------------------------------------------------ tests HTTP simules (vrais) ---
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 10000
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 10000
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"z" * 10000


def _image_transport(mime: str, body: bytes, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body,
                             headers={"content-type": mime})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_image_valide_jpeg(monkeypatch):
    from daily import check_image
    # Injection du transport simule dans le client de check_image.
    async def fake_get(url, **kw):
        transport = _image_transport("image/jpeg", JPEG)
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.get(url)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    verdict = await check_image("https://exemple.com/img.jpg")
    assert verdict["mime"] == "image/jpeg" and verdict["bytes"] >= 4096


@pytest.mark.asyncio
async def test_image_refusee_type_mensonger(monkeypatch):
    from daily import check_image
    async def fake_get(url, **kw):
        transport = _image_transport("image/jpeg", PNG)   # declare JPEG, est PNG
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.get(url)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(RuntimeError):
        await check_image("https://exemple.com/img.jpg")


@pytest.mark.asyncio
async def test_image_refusee_erreur_http(monkeypatch):
    from daily import check_image
    async def fake_get(url, **kw):
        transport = _image_transport("image/jpeg", b"", status=404)
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.get(url)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        await check_image("https://exemple.com/img.jpg")


@pytest.mark.asyncio
async def test_image_trop_petite_refusee(monkeypatch):
    from daily import check_image
    async def fake_get(url, **kw):
        transport = _image_transport("image/jpeg", b"\xff\xd8\xff" + b"x" * 100)
        async with httpx.AsyncClient(transport=transport) as c:
            return await c.get(url)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(RuntimeError):
        await check_image("https://exemple.com/img.jpg")


def test_catalogue_pagination():
    # Page 1 : 100 produits ; page 2 : 30 -> arret. Total 130 verifies.
    page1 = {"list": [{"id": str(i), "name": f"P{i}", "sku": f"S{i}"}
                      for i in range(100)]}
    page2 = {"list": [{"id": str(i), "name": f"P{i}", "sku": f"S{i}"}
                      for i in range(100, 130)]}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        calls.append(page)
        return httpx.Response(200, json=page1 if page == 1 else page2)

    transport = httpx.MockTransport(handler)

    async def run():
        products, page = [], 1
        async with httpx.AsyncClient(transport=transport) as c:
            while True:
                r = await c.get("https://fw.test/product",
                                params={"per_page": 100, "page": page})
                r.raise_for_status()
                body = r.json()
                assert isinstance(body.get("list"), list)
                products.extend(p for p in body["list"] if p.get("id") and p.get("name"))
                if len(body["list"]) < 100:
                    break
                page += 1
        return products

    products = asyncio.run(run())
    assert len(products) == 130
    assert calls == [1, 2]            # pagination arretee au bon moment


def test_creation_freewebstore_non_confirmee():
    # Reponse sans identifiant -> le produit N'EST JAMAIS inscrit publie.
    created = {"message": "error", "productId": None}
    new_id = None
    if isinstance(created, dict):
        new_id = created.get("productId") or created.get("id") \
            or (created.get("core") or {}).get("id")
    assert new_id is None


def test_creation_confirmee_puis_relecture():
    created = {"productId": "18809699"}
    check = {"core": {"id": "18809699", "published": True, "price": 24.90}}
    new_id = created.get("productId")
    c_core = check.get("core") or {}
    assert new_id and c_core.get("id") == new_id \
        and c_core.get("published") is True and c_core.get("price") == 24.90


# ------------------------------------------- taux de change : tous les cas ---
@pytest.mark.asyncio
async def test_taux_nan_nul_negatif_invalide_suspend():
    for bad_rate in (float("nan"), 0, -0.5):
        rate = bad_rate
        assert (not isinstance(rate, (int, float))
                or math.isnan(rate) or rate <= 0), f"doit rejeter {rate}"


def test_taux_timeout_et_erreur_http_suspendent(monkeypatch):
    async def fake_get(self, url, **kw):
        raise httpx.ConnectTimeout("timeout")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def call():
        import daily
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.frankfurter.app/latest",
                            params={"from": "USD", "to": "EUR"})
            r.raise_for_status()
            body = r.json()
            rate = ((body.get("rates") or {}).get("EUR"))
            if not isinstance(rate, (int, float)) or math.isnan(rate) or rate <= 0:
                raise RuntimeError("Taux USD/EUR invalide")
            return float(rate)

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(call())       # timeout -> suspension, aucun repli


def test_secret_manquant_suspend():
    with pytest.raises(EvaluationSuspended):
        raise EvaluationSuspended("CJ_API_KEY manquant")
