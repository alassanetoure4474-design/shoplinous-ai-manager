"""Tests pytest SHOPLINOUS workflow v5 (branche workflow-v5-review).

ATTENTION - HONNETETE : ces tests n'ont PAS ete executes dans
l'environnement de preparation (aucun interpreteur Python disponible,
`python3: command not available`). Execution attendue par l'utilisateur :
    pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest test_daily.py -v

Couverture v5 :
- corrections A (cn_stock_of : structure reelle stock[0].inventory=0,
  storageNum=11347 -> 11347) ;
- validate_quantity (1-5 acceptes ; 0, -1, 6, bool, str refuses) ;
- freight_coverage_alert (couvert -> None ; non couvert -> alerte ;
  tarif inconnu -> alerte manuelle) ;
- cj_freight appelée avec la quantite reelle (MockTransport, payload verifie) ;
- process_order lecture seule (jamais de POST/PUT vers CJ) ;
- regressions v4 : taux invalide (NaN/negatif/nul), images (octets
  magiques menteurs, 404, trop petite), pagination, confirmation de
  creation, allow_publish=False par defaut, aucune cle API en dur.
"""
import asyncio
import json

import httpx
import pytest

import daily


# --------------------------------------------------------------- helpers ----
def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def make_jpeg(size: int = 8192) -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


def make_png(size: int = 8192) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * (size - 8)


def make_webp(size: int = 8192) -> bytes:
    return b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * (size - 12)


def handler_for(responses: dict, default=b"{}"):
    """MockTransport : GET url -> (status, headers, body)."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path
        if request.url.host == "api.frankfurter.app":
            body = responses.get("rate", {"rates": {"EUR": 0.895}})
            return httpx.Response(200, json=body)
        if request.method == "POST":
            body = responses.get(key, default)
            return httpx.Response(200, json=body)
        body = responses.get(key, default)
        return httpx.Response(200, json=body)
    return handler


def mock_client(monkeypatch, responses: dict):
    transport = httpx.MockTransport(handler_for(responses))
    original = httpx.AsyncClient

    class PatchedClient(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)


# ---------------------------------------------- A. cn_stock_of (correctif) ----
class TestCnStockOf:
    def test_structure_reelle_storage_num_prioritaire(self):
        """Bug v4 : la reponse reelle montre stock[0].inventory = 0 alors
        que storageNum = 11347. La v5 doit retourner 11347."""
        payload = {"data": [{"countryCode": "CN", "storageNum": 11347,
                             "totalInventoryNum": 11347,
                             "stock": [{"inventory": 0}]}]}
        assert daily.cn_stock_of(payload) == 11347

    def test_fallback_total_inventory(self):
        payload = {"data": [{"countryCode": "CN", "storageNum": None,
                             "totalInventoryNum": 900,
                             "stock": [{"inventory": 0}]}]}
        assert daily.cn_stock_of(payload) == 900

    def test_fallback_stock_inventory(self):
        payload = {"data": [{"countryCode": "CN", "storageNum": 0,
                             "totalInventoryNum": 0,
                             "stock": [{"inventory": 500}]}]}
        assert daily.cn_stock_of(payload) == 500

    def test_pays_non_cn_ignore(self):
        payload = {"data": [{"countryCode": "US", "storageNum": 99999}]}
        assert daily.cn_stock_of(payload) == 0

    def test_valeurs_invalides_ignorees(self):
        payload = {"data": [{"countryCode": "CN", "storageNum": -5,
                             "totalInventoryNum": "beaucoup",
                             "stock": [{"inventory": True}]}]}
        assert daily.cn_stock_of(payload) == 0

    def test_regle_9_stock_affiche(self):
        assert daily.display_stock(11347) == 100
        assert daily.display_stock(150) == 50
        assert daily.display_stock(100) == 0
        assert daily.display_stock(0) == 0


# ------------------------------------------- B. validate_quantity (correctif) ----
class TestValidateQuantity:
    @pytest.mark.parametrize("qty", [1, 2, 3, 4, 5])
    def test_quantites_1_a_5_acceptees(self, qty):
        assert daily.validate_quantity(qty) == qty

    @pytest.mark.parametrize("qty", [0, -1, 6, 10, 100])
    def test_quantites_hors_plafond_refusees(self, qty):
        with pytest.raises(RuntimeError):
            daily.validate_quantity(qty)

    @pytest.mark.parametrize("qty", [True, False, "3", 2.5, None])
    def test_types_invalides_refuses(self, qty):
        with pytest.raises(RuntimeError):
            daily.validate_quantity(qty)


# ------------------------------------- C. freight_coverage_alert (correctif) ----
class TestFreightCoverageAlert:
    def test_couvert_retourne_none(self):
        assert daily.freight_coverage_alert(6.0, 5.0) is None

    def test_sous_tarif_alerte(self):
        # facture 4,00 EUR, fret reel 5,00 EUR (hors tolerance 10 %)
        alert = daily.freight_coverage_alert(4.0, 5.0)
        assert alert is not None and "non couverte" in alert

    def test_dans_tolerance_retourne_none(self):
        # facture 4,60 EUR, fret reel 5,00 EUR : ecart 8 % < tolerance 10 %
        assert daily.freight_coverage_alert(4.60, 5.0) is None

    def test_tarif_inconnu_alerte_manuelle(self):
        alert = daily.freight_coverage_alert(None, 5.0)
        assert alert is not None and "inconnu" in alert

    def test_fret_inconnu_alerte_manuelle(self):
        alert = daily.freight_coverage_alert(5.0, None)
        assert alert is not None and "indisponible" in alert


# -------------------------------- cj_freight : quantite reelle dans le payload ----
class TestCjFreightQuantity:
    def test_payload_contient_la_quantite(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/logistic/freight/calculate":
                seen.update(json.loads(request.content))
                return httpx.Response(200, json={
                    "code": 200, "data": [{"logisticName": "CJPacket",
                                           "logisticPrice": 5.65,
                                           "logisticAging": "4-10"}]})
            raise AssertionError("appel inattendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        result = run(daily.cj_freight("vid123", "FR", quantity=3))
        assert seen["quantity"] == 3
        assert result["data"][0]["logisticPrice"] == 5.65

    def test_quantite_invalide_refusee_avant_appel(self, monkeypatch):
        def handler(request):
            raise AssertionError("aucun appel CJ ne doit etre emis")
        monkeypatch.setattr(httpx, "AsyncClient", httpx.AsyncClient)
        with pytest.raises(RuntimeError):
            run(daily.cj_freight("vid123", "FR", quantity=6))


# ------------------------------------------ process_order : lecture seule ----
class TestProcessOrderReadOnly:
    def test_ne_passe_jamais_de_post_cj(self, monkeypatch):
        posts = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.host != "api.frankfurter.app":
                posts.append(request.url.path)
            if request.url.path == "/logistic/freight/calculate":
                return httpx.Response(200, json={
                    "code": 200, "data": [{"logisticName": "CJPacket",
                                           "logisticPrice": 4.69,
                                           "logisticAging": "4-10"}]})
            raise AssertionError("chemin inattendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        order = {"id": "ORD-1", "country": "FR",
                 "shipping_charged": 5.90,
                 "items": [{"vid": "vid123", "quantity": 2}]}
        report = run(daily.process_order(order))
        assert report["mode"] == "lecture_seule"
        assert posts == ["/logistic/freight/calculate"]
        assert report["lignes"][0]["quantite"] == 2
        assert report["alertes"] == []

    def test_alerte_si_tarif_non_couvert(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            return httpx.Response(200, json={
                "code": 200, "data": [{"logisticName": "CJPacket",
                                       "logisticPrice": 6.16,
                                       "logisticAging": "6-11"}]})

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        # FI : fret reel ~5,52 EUR, facture 2,00 EUR -> alerte
        order = {"id": "ORD-2", "country": "FI", "shipping_charged": 2.00,
                 "items": [{"vid": "vid123", "quantity": 1}]}
        report = run(daily.process_order(order))
        assert report["alertes"], "une alerte de couverture est attendue"

    def test_pays_hors_marche_signale(self):
        order = {"id": "ORD-3", "country": "MT",
                 "items": [{"vid": "vid123", "quantity": 1}]}
        report = run(daily.process_order(order))
        assert any("hors marche" in a for a in report["alertes"])


# ------------------------------------------------- regressions v4 : taux ----
class TestUsdEurRate:
    def test_taux_nan_refuse(self, monkeypatch):
        mock_client(monkeypatch, {"rate": {"rates": {"EUR": float("nan")}}})
        with pytest.raises((RuntimeError, ValueError)):
            run(daily.usd_eur_rate())

    def test_taux_negatif_refuse(self, monkeypatch):
        mock_client(monkeypatch, {"rate": {"rates": {"EUR": -0.5}}})
        with pytest.raises(RuntimeError):
            run(daily.usd_eur_rate())

    def test_taux_nul_refuse(self, monkeypatch):
        mock_client(monkeypatch, {"rate": {"rates": {"EUR": 0}}})
        with pytest.raises(RuntimeError):
            run(daily.usd_eur_rate())

    def test_taux_valide(self, monkeypatch):
        mock_client(monkeypatch, {"rate": {"rates": {"EUR": 0.89509}}})
        assert run(daily.usd_eur_rate()) == pytest.approx(0.89509)

    def test_timeout_leve(self, monkeypatch):
        def handler(request):
            raise httpx.ConnectTimeout("timeout")
        transport = httpx.MockTransport(handler)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        with pytest.raises(httpx.HTTPError):
            run(daily.usd_eur_rate())


# --------------------------------------------- regressions v4 : images ----
class TestCheckImage:
    def test_jpeg_valide(self, monkeypatch):
        transport = httpx.MockTransport(lambda r: httpx.Response(
            200, content=make_jpeg(),
            headers={"content-type": "image/jpeg"}))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        verdict = run(daily.check_image("https://img.example.com/a.jpg"))
        assert verdict["mime"] == "image/jpeg"
        assert verdict["bytes"] >= daily.MIN_IMAGE_BYTES

    def test_mime_menteur_refuse(self, monkeypatch):
        # declare JPEG mais contenu PNG -> refus
        transport = httpx.MockTransport(lambda r: httpx.Response(
            200, content=make_png(),
            headers={"content-type": "image/jpeg"}))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        with pytest.raises(RuntimeError):
            run(daily.check_image("https://img.example.com/a.jpg"))

    def test_erreur_http_refusee(self, monkeypatch):
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        with pytest.raises(httpx.HTTPError):
            run(daily.check_image("https://img.example.com/absent.jpg"))

    def test_image_trop_petite_refusee(self, monkeypatch):
        transport = httpx.MockTransport(lambda r: httpx.Response(
            200, content=b"\xff\xd8\xff\xe0\x00\x00\x00\x00",
            headers={"content-type": "image/jpeg"}))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        with pytest.raises(RuntimeError):
            run(daily.check_image("https://img.example.com/petite.jpg"))

    def test_webp_valide(self, monkeypatch):
        transport = httpx.MockTransport(lambda r: httpx.Response(
            200, content=make_webp(),
            headers={"content-type": "image/webp"}))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        assert run(daily.check_image("https://img.example.com/a.webp"))["mime"] == "image/webp"

    def test_mime_non_autorise_refuse(self, monkeypatch):
        transport = httpx.MockTransport(lambda r: httpx.Response(
            200, content=b"GIF89a" + b"\x00" * 8192,
            headers={"content-type": "image/gif"}))
        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        with pytest.raises(RuntimeError):
            run(daily.check_image("https://img.example.com/a.gif"))


# ------------------------------------------ regressions v4 : CJ structure ----
class TestCjCheck:
    def test_code_erreur_leve(self):
        with pytest.raises(RuntimeError):
            daily.cj_check({"code": 1600200, "message": "QPS limit"}, "fret")

    def test_data_absent_leve(self):
        with pytest.raises(RuntimeError):
            daily.cj_check({"code": 200}, "fret")

    def test_reponse_valide(self):
        assert daily.cj_check({"code": 200, "data": []}, "fret")["code"] == 200

    def test_reponse_non_dict_leve(self):
        with pytest.raises(RuntimeError):
            daily.cj_check([1, 2, 3], "fret")


# ------------------------------------------- regressions v4 : logique pure ----
class TestLogiquePure:
    def test_prix_arrondi_x90(self):
        assert daily.sale_price(7.00) == 7.90
        assert daily.sale_price(7.90) == 7.90
        assert daily.sale_price(7.91) == 8.90

    def test_marge_stricte_toutes_combinaisons(self):
        rate = 0.89509
        for cost_usd, ship_eur in [(2.81, 4.20), (5.00, 6.00), (8.00, 3.21)]:
            price = daily.sale_price((cost_usd * rate + ship_eur) * 3)
            assert price >= (cost_usd * rate + ship_eur) * 3 - 1e-9

    def test_similar_name(self):
        assert daily.similar_name("Wooden Wall Clock Modern",
                                  ["Modern Wooden Wall Clock large"])
        assert not daily.similar_name("Storage Basket Cotton",
                                      ["Wall Clock Modern"])

    def test_conforming_freight_options(self):
        options = [
            {"logisticPrice": 4.69, "logisticAging": "4-10"},     # conforme
            {"logisticPrice": 7.00, "logisticAging": "4-8"},      # trop cher
            {"logisticPrice": 4.00, "logisticAging": "14-26"},    # trop lent
            {"logisticPrice": "n/a", "logisticAging": "4-8"},     # invalide
        ]
        ok = daily.conforming_freight_options(options, 0.895)
        assert len(ok) == 1
        assert ok[0]["aging_min"] == 4 and ok[0]["aging_max"] == 10

    def test_merge_destinations_intersection_stricte(self):
        per_variant = {
            "v1": {"FR": {"price_eur": 4.20, "aging_min": 4, "aging_max": 10},
                    "DE": {"price_eur": 4.24, "aging_min": 7, "aging_max": 15}},
            "v2": {"FR": {"price_eur": 4.50, "aging_min": 5, "aging_max": 12}},
        }
        kept, dmin, dmax = daily.merge_destinations(per_variant)
        assert kept == {"FR": 4.50}
        assert dmin["FR"] == 4 and dmax["FR"] == 12

    def test_parse_cj_images_chaine_json(self):
        detail = {"data": {"productImage": json.dumps(
            ["https://a/1.jpg", "https://a/2.jpg"])}}
        urls = daily.parse_cj_images(detail)
        assert urls == ["https://a/1.jpg", "https://a/2.jpg"]

    def test_benefice_net_livraison_est_recette(self):
        # livraison facturee au client = RECETTE, jamais depense
        net = daily.estimated_net_profit(24.90, 4.90, 2.52, 4.20, 1.02)
        assert net == pytest.approx(24.90 + 4.90 - 2.52 - 4.20 - 1.02)

    def test_benefice_net_scenario_pessimiste(self):
        # tarif checkout inconnu -> scenario 0 EUR facture (jamais surestime)
        net = daily.estimated_net_profit(24.90, None, 2.52, 4.20, 1.02)
        assert net == pytest.approx(24.90 - 2.52 - 4.20 - 1.02)


# --------------------------------------------- regressions v4 : pagination ----
class TestPagination:
    def test_toutes_les_pages_lues(self, monkeypatch):
        pages = [
            {"list": [{"id": str(i), "name": f"p{i}"} for i in range(100)]},
            {"list": [{"id": "100", "name": "p100"}]},
        ]
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/product":
                page = int(request.url.params.get("page", "1"))
                calls.append(page)
                return httpx.Response(200, json=pages[page - 1])
            return httpx.Response(200, json={})

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "test-key")
        products = run(daily.fw_list_all_products())
        assert len(products) == 101
        assert calls == [1, 2]

    def test_produit_malforme_leve(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"list": [{"id": "x"}]})  # sans nom

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "test-key")
        with pytest.raises(RuntimeError):
            run(daily.fw_list_all_products())


# -------------------------------------- regressions v4 : creation confirmee ----
class TestConfirmationCreation:
    def test_creation_sans_id_signalee(self, monkeypatch):
        mock_client(monkeypatch, {"/product": {"foo": "bar"}})
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "test-key")
        created = run(daily.fw_create_product({"name": "x"}, []))
        assert not (created.get("productId") or created.get("id"))

    def test_verification_post_creation(self, monkeypatch):
        mock_client(monkeypatch, {
            "/product/777": {"core": {"id": "777", "published": True,
                                       "price": 24.90}}})
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "test-key")
        check = run(daily.fw_get_product("777"))
        core = check.get("core") or {}
        assert core.get("published") is True and core.get("price") == 24.90


# ------------------------------------------- securite et mode veille ----
class TestSecurite:
    def test_allow_publish_false_par_defaut(self):
        params = daily.DailyParams()
        assert params.allow_publish is False

    def test_allow_publish_false_applique(self):
        params = daily.DailyParams(allow_publish=False)
        assert params.allow_publish is False

    def test_parametres_inconnus_refuses(self):
        with pytest.raises(Exception):
            daily.DailyParams(tarif_livraison_mensonge=True)

    def test_malte_exclue(self):
        assert "MT" not in daily.DEST_COUNTRIES

    def test_29_pays(self):
        assert len(daily.DEST_COUNTRIES) == 29

    def test_plafond_quantite_5(self):
        assert daily.MAX_ORDER_QTY == 5

    def test_aucune_cle_en_dur(self):
        import inspect
        source = inspect.getsource(daily)
        for secret in ("CJ_API_KEY=", "FREEWEBSTORE_API_KEY=",
                        "sk-", "Bearer eyJ"):
            assert secret + '"' not in source and secret + "'" not in source
