"""Tests pytest SHOPLINOUS workflow v5 (branche workflow-v5-review).

HONNETETE : non executes dans l'environnement de preparation
(aucun Python disponible). EXECUTION REELLE via GitHub Actions sur la
branche workflow-v5-fix1 (.github/workflows/python-tests.yml), egalement
executable localement :
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
- v5.1 : process_order APPELE par le workflow pour chaque commande,
- v5.2 : compatibilite REELLE Freewebstore (structure observee
  GET /orders et /orders/abandoned) : adaptateur securise
  fw_normalize_order, pagination limit/offset, en-tete x-api-key,
  fixtures reelles anonymisees, zero donnee personnelle ;
  repartition multi-lignes securisee, > 5 unites, protection fournisseur ;
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
            if request.url.path.endswith("/logistic/freight/calculate"):
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
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            if request.url.path.endswith("/logistic/freight/calculate"):
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
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        order = {"id": "ORD-1", "country": "FR",
                 "shipping_charged": 5.90,
                 "items": [{"vid": "vid123", "quantity": 2}]}
        report = run(daily.process_order(order))
        assert report["mode"] == "lecture_seule"
        assert len(posts) == 1 and posts[0].endswith("/logistic/freight/calculate")
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


# ================= process_order v5.1 : tests dedies (correctif) =================
class TestProcessOrderV51:
    """Analyse COMPLETE de process_order avec commandes simulees :
    1 ligne, plusieurs lignes, quantite invalide, pays inconnu,
    fret indisponible, tarif insuffisant, > 5 unites, protection
    fournisseur (aucune creation ni modification de commande CJ)."""

    def _mock(self, monkeypatch, rate=0.895, freights=None, rate_down=False):
        """Mock httpx : retourne la liste des requetes emises."""
        calls = []
        if freights is None:
            freights = [{"logisticName": "CJPacket",
                         "logisticPrice": 4.69,
                         "logisticAging": "4-10"}]

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.host,
                          request.url.path))
            if request.url.host == "api.frankfurter.app":
                if rate_down:
                    return httpx.Response(500)
                return httpx.Response(200, json={"rates": {"EUR": rate}})
            if request.url.path.endswith("/logistic/freight/calculate"):
                return httpx.Response(200, json={
                    "code": 200, "data": freights})
            raise AssertionError(
                "endpoint non autorise : " + request.method + " "
                + str(request.url))

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        return calls

    def test_une_ligne_valide(self, monkeypatch):
        calls = self._mock(monkeypatch, freights=[
            {"logisticName": "CJPacket", "logisticPrice": 5.65,
             "logisticAging": "4-10"}])
        order = {"id": "O1", "country": "FR", "shipping_charged": 5.90,
                 "items": [{"vid": "v1", "quantity": 2}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "verifie"
        assert rep["repartition_livraison"] == "total_commande"
        assert rep["fret_total_eur"] == 5.06   # 5.65 USD x 0.895
        assert rep["lignes"][0]["statut"] == "verifie"
        assert rep["alertes"] == []
        assert all(p.endswith("/logistic/freight/calculate")
                   for m, h, p in calls if h != "api.frankfurter.app")

    def test_multi_lignes_tarif_par_ligne(self, monkeypatch):
        calls = self._mock(monkeypatch)
        order = {"id": "O2", "country": "FR", "items": [
            {"vid": "v1", "quantity": 1, "shipping_charged": 4.50},
            {"vid": "v2", "quantity": 3, "shipping_charged": 8.00}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "verifie"
        assert rep["repartition_livraison"] == "par_ligne"
        assert rep["lignes"][0]["tarif_facture_eur"] == 4.50
        assert rep["lignes"][1]["tarif_facture_eur"] == 8.00
        fret_posts = [c for c in calls if c[2].endswith("/logistic/freight/calculate")]
        assert len(fret_posts) == 2

    def test_multi_lignes_repartition_totale(self, monkeypatch):
        """Tarif global uniquement : UNE comparaison au niveau commande,
        aucune repartition inventee entre les lignes."""
        self._mock(monkeypatch)
        order = {"id": "O3", "country": "FR", "shipping_charged": 12.00,
                 "items": [{"vid": "v1", "quantity": 1},
                           {"vid": "v2", "quantity": 2}]}
        rep = run(daily.process_order(order))
        assert rep["repartition_livraison"] == "total_commande"
        assert rep["fret_total_eur"] == 8.4    # 2 x 4.69 USD x 0.895 = 8.3971
        assert "tarif_facture_eur" not in rep["lignes"][0]
        assert rep["statut"] == "verifie"

    def test_tarif_insuffisant_alerte(self, monkeypatch):
        self._mock(monkeypatch)
        order = {"id": "O4", "country": "FR", "shipping_charged": 1.00,
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "alertes"
        assert any("non couverte" in a for a in rep["alertes"])

    def test_tarif_totalement_inconnu(self, monkeypatch):
        self._mock(monkeypatch)
        order = {"id": "O5", "country": "FR",
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["repartition_livraison"] == "inconnue"
        assert any("inconnu" in a for a in rep["alertes"])
        assert rep["statut"] == "alertes"

    def test_quantite_invalide_aucun_appel_cj(self, monkeypatch):
        calls = self._mock(monkeypatch)
        order = {"id": "O6", "country": "FR", "shipping_charged": 5.00,
                 "items": [{"vid": "v1", "quantity": "beaucoup"}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][0]["statut"] == "quantite_invalide"
        assert rep["statut"] == "lignes_non_verifiees"
        assert all(h == "api.frankfurter.app" for m, h, p in calls)

    def test_quantite_superieure_a_5_explicite(self, monkeypatch):
        calls = self._mock(monkeypatch)
        order = {"id": "O7", "country": "FR", "shipping_charged": 15.00,
                 "items": [{"vid": "v1", "quantity": 7}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][0]["statut"] == "depasse_plafond"
        assert any("verification manuelle" in a for a in rep["alertes"])
        assert all(h == "api.frankfurter.app" for m, h, p in calls)
        assert rep["statut"] == "lignes_non_verifiees"

    def test_pays_inconnu_aucun_appel(self, monkeypatch):
        calls = self._mock(monkeypatch)
        order = {"id": "O8", "country": "US",
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "hors_marche"
        assert calls == []

    def test_malte_hors_marche(self, monkeypatch):
        self._mock(monkeypatch)
        order = {"id": "O9", "country": "MT",
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "hors_marche"

    def test_fret_indisponible(self, monkeypatch):
        """Erreur metier CJ (ex. code 1600200) -> statut fret_indisponible,
        alerte, lecture seule conservee."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.host,
                          request.url.path))
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            return httpx.Response(200, json={
                "code": 1600200, "message": "erreur CJ",
                "data": None})

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        order = {"id": "O10", "country": "FR", "shipping_charged": 5.00,
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][0]["statut"] == "fret_indisponible"
        assert rep["statut"] == "lignes_non_verifiees"
        assert any("fret non verifiable" in a for a in rep["alertes"])

    def test_aucune_option_de_fret(self, monkeypatch):
        self._mock(monkeypatch, freights=[])
        order = {"id": "O11", "country": "FR", "shipping_charged": 5.00,
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][0]["statut"] == "fret_indisponible"

    def test_taux_indisponible(self, monkeypatch):
        self._mock(monkeypatch, rate_down=True)
        order = {"id": "O12", "country": "FR",
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        assert rep["statut"] == "taux_indisponible"

    def test_commande_sans_lignes(self, monkeypatch):
        self._mock(monkeypatch)
        rep = run(daily.process_order({"id": "O13", "country": "FR",
                                       "items": []}))
        assert rep["statut"] == "sans_lignes"

    def test_ligne_sans_vid(self, monkeypatch):
        self._mock(monkeypatch)
        order = {"id": "O14", "country": "FR", "shipping_charged": 5.00,
                 "items": [{"quantity": 2}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][0]["statut"] == "sans_vid"

    def test_multi_lignes_avec_ligne_ko_comparaison_annulee(self, monkeypatch):
        """Une ligne > 5 unites : le total fret est incomplet, la
        comparaison au niveau commande doit etre ANNULEE (securite)."""
        self._mock(monkeypatch)
        order = {"id": "O15", "country": "FR", "shipping_charged": 20.00,
                 "items": [{"vid": "v1", "quantity": 1},
                           {"vid": "v2", "quantity": 9}]}
        rep = run(daily.process_order(order))
        assert rep["lignes"][1]["statut"] == "depasse_plafond"
        assert any("ANNULEE" in a for a in rep["alertes"])
        assert rep["statut"] == "lignes_non_verifiees"

    def test_protection_aucune_creation_commande_fournisseur(self, monkeypatch):
        """process_order ne doit toucher AUCUN endpoint d'ordre fournisseur :
        verifie les appels emis ET le code source de l'activite."""
        calls = self._mock(monkeypatch)
        order = {"id": "O16", "country": "FR", "shipping_charged": 5.00,
                 "items": [{"vid": "v1", "quantity": 1}]}
        rep = run(daily.process_order(order))
        for method, host, path in calls:
            if host == "api.frankfurter.app":
                assert method == "GET"
            else:
                assert (method == "POST"
                                          and path.endswith("/logistic/freight/calculate"))
        import inspect
        src = inspect.getsource(daily.process_order)
        for forbidden in ("shopping/order", "purchase", "createOrder",
                          "cancelOrder", "payOrder"):
            assert forbidden not in src, "endpoint interdit : " + forbidden

    def test_workflow_appelle_process_order_pour_chaque_commande(self):
        """Le workflow run() doit reellement appeler process_order sur
        chaque commande recue (bug v5 : simple comptage)."""
        import inspect
        src = inspect.getsource(daily.ShoplinousDailyWorkflow)
        assert "await process_order(\n                        fw_normalize_order(o), vid_table=vid_table)" in src
        assert "orders_analyzed" in src


# ================= v5.2 : compatibilite REELLE Freewebstore =================
# Structures observees en lecture seule le 01/11/2026 (storeid 1107499) :
# GET /orders -> {"orders": {"found": 0, "count": 0, "matched": 0,
#                            "duration": 44, "orders": [], "flux": null}}
# GET /orders/abandoned -> 2 paniers avec la structure COMPLETE ci-dessous.
# Les fixtures sont des exemples REELS ANONYMISES : toutes les donnees
# personnelles (nom, email, telephone, adresse, IP, session) ont ete
# remplacees ; les champs metier (id, storeid, productId, productSKU CJ,
# variantId FW, quantity, net, postage, country_iso_2) sont exacts.
FW_PANIER_REEL_FR = {
    "storeid": "1107499",
    "id": "3i9VP7j",
    "net": 24.9, "tax": 0.0,
    "postage": 0.0, "postage_tax": 0.0, "discount": 0.0,
    "currency": "EUR",
    "paymentmethod": "PREPOST",
    "order_status": 0,
    "origin_country": "FR",
    "delivery_address": {
        "forename": "CLIENT", "surname": "ANONYME",
        "address1": "ADRESSE", "city": "VILLE", "county": "DEPARTEMENT",
        "country": "France", "country_iso_2": "FR", "country_iso_3": "FRA",
        "postcode": "00000", "telephone": "0000000000",
    },
    "order_details": [
        {
            "productId": "18809643",
            "productSKU": "CJJT205244502BY",
            "productName": "Attrape-reves Indien Boheme 40 cm - Decoration Murale",
            "variantId": "WPPmLB",
            "variantName": "Couleur:Noir",
            "net": 24.9, "tax": 0.0,
            "quantity": 1,
            "weight": 0.0, "weightUnits": "g",
            "currency": "EUR",
        }
    ],
    "postage_audit": {"ruleName": "standard", "net": 0.0,
                      "method": 0, "totalWeight": 0.0, "originalNet": 0.0},
    "tags": ["new"],
}

FW_PANIER_REEL_CI = {
    "storeid": "1107499",
    "id": "crwmdzh",
    "net": 24.9,
    "postage": 0.0, "postage_tax": 0.0,
    "currency": "EUR",
    "paymentmethod": "PREPOST",
    "order_status": 0,
    "delivery_address": {
        "forename": "CLIENT", "surname": "ANONYME",
        "address1": "ADRESSE", "city": "VILLE",
        "country": "Cote d'Ivoire", "country_iso_2": "CI",
        "postcode": "00000", "telephone": "0000000000",
    },
    "order_details": [
        {
            "productId": "18809643",
            "productSKU": "CJJT205244502BY",
            "variantId": "WPPmLB",
            "net": 24.9,
            "quantity": 1,
            "currency": "EUR",
        }
    ],
    "postage_audit": {"ruleName": "standard", "net": 0.0},
    "tags": ["new"],
}


class TestFwCompatV52:
    """v5.2 : compatibilite reelle Freewebstore - adaptateur securise,
    pagination /orders, en-tete x-api-key, anonymisation, protection."""

    def test_enveloppe_reelle_orders_orders_imbrique(self):
        """La vraie reponse GET /orders est {"orders": {..., "orders": []}}
        (2 niveaux) : l'adaptateur doit fonctionner sur cette structure."""
        raw = {"orders": {"found": 0, "count": 0, "matched": 0,
                          "duration": 44, "orders": [], "flux": None}}
        norm = daily.fw_normalize_order(raw["orders"]["orders"])
        assert norm["items"] == [] and norm["id"] is None

    def test_fw_orders_pagination_deux_pages(self, monkeypatch):
        """GET /orders avec limit/offset : 2 pages -> toutes les commandes
        recuperees, 'found' conserve, en-tete x-api-key emis."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.url.path,
                          request.url.params.get("limit"),
                          request.url.params.get("offset"),
                          request.headers.get("x-api-key")))
            offset = int(request.url.params.get("offset", "0"))
            if offset == 0:
                batch = [{"id": "A"}, {"id": "B"}]
            else:
                batch = [{"id": "C"}]
            return httpx.Response(200, json={
                "orders": {"found": 3, "count": 3, "matched": 3,
                           "duration": 30, "orders": batch, "flux": None}})

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "fw-key-123")
        result = run(daily.fw_orders())
        assert result["found"] == 3
        assert [o["id"] for o in result["orders"]] == ["A", "B", "C"]
        assert len(calls) == 2
        assert calls[0][0].endswith("/orders")
        assert calls[0][1] == "50" and calls[0][2] == "0"
        assert calls[1][2] == "2"
        # en-tete x-api-key (methode CONFIRMEE par la doc officielle)
        assert calls[0][3] == "fw-key-123"

    def test_fw_orders_uri_orders_pas_order(self, monkeypatch):
        """L'URI REELLE est /orders (pluriel) - pas /order."""
        paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={
                "orders": {"found": 0, "orders": []}})

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "fw-key-123")
        result = run(daily.fw_orders())
        assert result == {"found": 0, "orders": []}
        assert paths[-1].endswith("/orders")

    def test_entete_x_api_key_pas_bearer(self, monkeypatch):
        """_fw_headers doit emettre x-api-key (doc officielle), pas Bearer."""
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "fw-key-123")
        headers = daily._fw_headers()
        assert headers.get("x-api-key") == "fw-key-123"
        assert "Authorization" not in headers

    def test_normalize_exemple_reel_fr(self):
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        assert norm["id"] == "3i9VP7j"
        assert norm["country"] == "FR"
        assert norm["shipping_charged"] == 0.0
        assert norm["source"] == "freewebstore"
        assert len(norm["items"]) == 1
        item = norm["items"][0]
        assert item["vid"] is None          # vid CJ non transporte par FW
        assert item["sku"] == "CJJT205244502BY"
        assert item["product_id"] == "18809643"
        assert item["quantity"] == 1
        assert item["prix_ligne_eur"] == 24.9

    def test_normalize_exemple_reel_ci(self):
        norm = daily.fw_normalize_order(FW_PANIER_REEL_CI)
        assert norm["country"] == "CI"
        assert norm["id"] == "crwmdzh"

    def test_normalize_copie_aucune_donnee_personnelle(self):
        """SECURITE : la sortie normalisee ne doit contenir QUE des champs
        metier (liste blanche EXACTE, verifiee recursivement sur toutes
        les cles) et aucune valeur personnelle des fixtures."""
        AUTORISES = {"id", "country", "shipping_charged", "items", "source",
                     "vid", "sku", "product_id", "quantity", "prix_ligne_eur"}
        for fixture in (FW_PANIER_REEL_FR, FW_PANIER_REEL_CI):
            norm = daily.fw_normalize_order(fixture)
            cles = set()

            def collecte(obj):
                if isinstance(obj, dict):
                    cles.update(obj.keys())
                    for v in obj.values():
                        collecte(v)
                elif isinstance(obj, list):
                    for v in obj:
                        collecte(v)
            collecte(norm)
            hors_liste = cles - AUTORISES
            assert not hors_liste, "cles hors liste blanche : " + repr(hors_liste)
            blob = json.dumps(norm).lower()
            assert "anonyme" not in blob
            assert "0000000000" not in blob
            assert "adresse" not in blob
            assert "ville" not in blob

    def test_normalize_mauvaise_entree(self):
        norm = daily.fw_normalize_order("n'importe quoi")
        assert norm["id"] is None and norm["items"] == []

    def test_process_order_sur_commande_normalisee_fr(self, monkeypatch):
        """Pipeline complet : commande FW reelle normalisee -> process_order.
        Le vid CJ etant non transporte : ligne sans_vid avec SKU dans
        l'alerte, comparaison au total ANNULEE, AUCUN appel CJ emis."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            raise AssertionError("endpoint inattendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        rep = run(daily.process_order(norm))
        assert rep["order_id"] == "3i9VP7j"
        assert rep["pays"] == "FR"
        assert rep["repartition_livraison"] == "total_commande"
        ligne = rep["lignes"][0]
        assert ligne["statut"] == "sans_vid"
        assert ligne["sku"] == "CJJT205244502BY"
        assert any("CJJT205244502BY" in a for a in rep["alertes"])
        assert any("verification manuelle" in a for a in rep["alertes"])
        assert rep["statut"] == "lignes_non_verifiees"
        assert any("ANNULEE" in a for a in rep["alertes"])
        # aucune donnee personnelle ne transite vers process_order
        blob = json.dumps(rep).lower()
        assert "anonyme" not in blob and "0000000000" not in blob

    def test_process_order_sur_commande_normalisee_ci(self, monkeypatch):
        """Panier CI reel : pays hors marche (marche = UE27+GB/CH/NO),
        signale sans AUCUN appel reseau CJ."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("aucun appel attendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        norm = daily.fw_normalize_order(FW_PANIER_REEL_CI)
        rep = run(daily.process_order(norm))
        assert rep["statut"] == "hors_marche"
        assert rep["pays"] == "CI"

    def test_workflow_normalise_avant_process(self):
        """Le workflow doit appliquer l'adaptateur securise fw_normalize_order
        AVANT process_order (jamais de commande brute avec donnees perso)."""
        import inspect
        src = inspect.getsource(daily.ShoplinousDailyWorkflow)
        assert "vid_table=vid_table" in src
        assert "fw_normalize_order(o), vid_table=vid_table)" in src.replace("\n", " ")
        assert "await process_order(o)" not in src
        # v5.3 : la table est reconstruite en lecture seule a chaque run
        assert "build_vid_table(fw_records)" in src
        assert "VID_TABLE_SEED" in src

    def test_protection_aucune_ecriture_boutique(self, monkeypatch):
        """fw_orders + fw_normalize + process_order n'emettent AUCUN
        POST/PUT/PATCH vers Freewebstore (lecture seule integrale) et
        aucun achat fournisseur CJ."""
        writes = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            if request.method != "GET":
                writes.append(request.method + " " + request.url.path)
            if request.url.path.endswith("/orders"):
                return httpx.Response(200, json={
                    "orders": {"found": 1, "orders": [FW_PANIER_REEL_FR]}})
            raise AssertionError("endpoint inattendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("FREEWEBSTORE_API_KEY", "fw-key-123")
        monkeypatch.setenv("CJ_API_KEY", "test-key")
        body = run(daily.fw_orders())
        norm = daily.fw_normalize_order(body["orders"][0])
        rep = run(daily.process_order(norm))
        assert writes == []
        assert rep["mode"] == "lecture_seule"
        import inspect
        src_orders = inspect.getsource(daily.fw_orders)
        assert "POST" not in src_orders
        src_norm = inspect.getsource(daily.fw_normalize_order)
        for interdit in ("requests.post", "httpx.post"):
            assert interdit not in src_norm


# ============ v5.3 : table SKU->vid (correspondance FW -> CJ) ============
# Donnees REELLES observees en lecture seule le 02/11/2026 :
# - GET /product (storeid 1107499) : 12 produits, dont 11 produits demo
#   (sku yellow0001... non-CJ) et 1 produit SHOPLINOUS publie :
#   id 18809643, sku SHP-CJT2052445, 2 variantes.
# - GET /product/18809643 : variants[] avec 'uvid' (= variantId des
#   commandes) : ZsKQFt/CJJT205244501AZ (Blanc), WPPmLB/CJJT205244502BY
#   (Noir).
# - Recherche CJ par SKU DE VARIANTE : "CJJT205244501AZ" et
#   "CJJT205244502BY" -> produit UNIQUE pid 1797521453303214080
#   (sku CJJT2052445).
# - Variantes CJ : vid 1797521453382905856 (CJJT205244501AZ, White-40cm),
#   vid 1797521453454209024 (CJJT205244502BY, Black-40cm).
# NB : la recherche CJ par SKU de PRODUIT ("CJT2052445") retourne 0 :
# la recherche par SKU de VARIANTE est la methode confirmee.
FW_DETAIL_ATTRAPE_REEL = {
    "productId": None,
    "core": {"id": "18809643", "sku": "SHP-CJT2052445",
             "name": "Attrape-reves Indien Boheme 40 cm",
             "price": 24.9, "published": True, "brand": "SHOPLINOUS"},
    "variants": [
        {"uvid": "ZsKQFt", "key": "Couleur:Blanc",
         "sku": "CJJT205244501AZ", "label": "Couleur:Blanc",
         "stock": 100, "condition": "New", "sequence": 1},
        {"uvid": "WPPmLB", "key": "Couleur:Noir",
         "sku": "CJJT205244502BY", "label": "Couleur:Noir",
         "stock": 100, "condition": "New", "sequence": 2},
    ],
}
FW_CATALOGUE_REEL = [
    {"id": "38968614", "sku": "yellow0001", "name": "Yellow Wrap Tunic Top",
     "published": False},
    {"id": "18809643", "sku": "SHP-CJT2052445",
     "name": "Attrape-reves Indien Boheme 40 cm", "published": True},
]
CJ_SEARCH_REEL = {
    "code": 200, "result": True, "message": "Success",
    "data": {"content": [
        {"productList": [
            {"id": "1797521453303214080", "sku": "CJJT2052445",
             "nameEn": "Indian Dreamcatcher Home Decoration Pendant",
             "sellPrice": "2.81"},
        ]},
    ]},
}
CJ_VARIANTES_ATTRAPE_REEL = [
    {"vid": "1797521453382905856", "pid": "1797521453303214080",
     "variantSku": "CJJT205244501AZ", "variantKey": "White-40cm",
     "variantSellPrice": "2.81", "variantWeight": 80},
    {"vid": "1797521453454209024", "pid": "1797521453303214080",
     "variantSku": "CJJT205244502BY", "variantKey": "Black-40cm",
     "variantSellPrice": "2.81", "variantWeight": 80},
]
FW_RECORDS_ATTRAPE_REEL = [
    {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
     "fw_variant_id": "ZsKQFt", "variant_sku": "CJJT205244501AZ"},
    {"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
     "fw_variant_id": "WPPmLB", "variant_sku": "CJJT205244502BY"},
]


def _async(v):
    async def fn(*a, **kw):
        return v
    return fn


class TestVidTableV53:
    """v5.3 : correspondances EXACTES SKU + variante, cas ambigus et
    absents, protection lecture seule, amorce verifiee."""

    def test_fw_variant_records_extrait_uvid_et_sku(self, monkeypatch):
        """Le variantId des commandes = champ 'uvid' du detail produit
        (structure reelle du 02/11/2026)."""
        monkeypatch.setattr(daily, "fw_get_product",
                            _async(FW_DETAIL_ATTRAPE_REEL))
        recs = run(daily.fw_variant_records(FW_CATALOGUE_REEL))
        ids = {(r["fw_variant_id"], r["variant_sku"]) for r in recs}
        assert ids == {("ZsKQFt", "CJJT205244501AZ"),
                       ("WPPmLB", "CJJT205244502BY")}
        assert all(r["fw_product_id"] == "18809643" for r in recs)

    def test_build_table_correspondances_exactes_reelles(self):
        """Cas REEL : les 2 SKU FW correspondent exactement aux 2 SKU CJ
        -> 2 entrees avec les vrais vids."""
        res = run(daily.build_vid_table(
            [dict(r) for r in FW_RECORDS_ATTRAPE_REEL],
            cj_search_fn=_async(CJ_SEARCH_REEL),
            cj_variants_fn=_async({"code": 200, "result": True,
                                   "data": CJ_VARIANTES_ATTRAPE_REEL})))
        t = res["table"]
        assert set(t) == {"CJJT205244501AZ", "CJJT205244502BY"}
        assert t["CJJT205244501AZ"]["vid"] == "1797521453382905856"
        assert t["CJJT205244502BY"]["vid"] == "1797521453454209024"
        assert t["CJJT205244501AZ"]["fw_variant_id"] == "ZsKQFt"
        assert t["CJJT205244502BY"]["fw_variant_id"] == "WPPmLB"
        assert t["CJJT205244502BY"]["cj_pid"] == "1797521453303214080"
        assert res["ambigus"] == [] and res["absents"] == []
        assert res["nb_variantes_fw"] == 2

    def test_build_table_absent_sans_produit_candidat(self):
        """Produit demo (SKU non-CJ) : recherche vide -> absent,
        sans_vid conserve, AUCUNE approximation."""
        res = run(daily.build_vid_table(
            [{"fw_product_id": "38968614", "fw_variant_id": "x",
              "variant_sku": "yellow0001"}],
            cj_search_fn=_async({"data": {"content": [
                {"productList": []}]}}),
            cj_variants_fn=_async({"data": []})))
        assert res["table"] == {}
        assert len(res["absents"]) == 1
        assert res["absents"][0]["variant_sku"] == "yellow0001"
        assert res["ambigus"] == []

    def test_build_table_aucune_approximation_sku(self):
        """SKU tronque ou casse differente : JAMAIS associe (exactitude
        stricte)."""
        for faux_sku in ("CJJT205244502B", "cjjt205244502by",
                         " CJJT205244502BY"):
            res = run(daily.build_vid_table(
                [{"fw_product_id": "18809643", "fw_variant_id": "W",
                  "variant_sku": faux_sku}],
                cj_search_fn=_async(CJ_SEARCH_REEL),
                cj_variants_fn=_async({"code": 200, "result": True,
                                       "data": CJ_VARIANTES_ATTRAPE_REEL})))
            assert res["table"] == {}, faux_sku
            assert res["absents"], faux_sku

    def test_build_table_ambigu_deux_candidats(self):
        """Deux produits CJ candidats avec le meme SKU exact mais des
        vids differents -> AMBIGU, pas d'association."""
        search2 = {"code": 200, "result": True, "data": {"content": [
            {"productList": [
                {"id": "1797521453303214080", "sku": "CJJT2052445"},
                {"id": "1111111111111111111", "sku": "CJJT9999999"},
            ]}]}}
        variants2 = {"code": 200, "result": True, "data": [
            {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY"},
            {"vid": "2222222222222222222", "variantSku": "CJJT205244502BY"},
        ]}
        res = run(daily.build_vid_table(
            [{"fw_product_id": "18809643", "fw_variant_id": "WPPmLB",
              "variant_sku": "CJJT205244502BY"}],
            cj_search_fn=_async(search2),
            cj_variants_fn=_async(variants2)))
        assert res["table"] == {}
        assert len(res["ambigus"]) == 1
        assert res["ambigus"][0]["variant_sku"] == "CJJT205244502BY"
        assert len(res["ambigus"][0]["candidats_vid"]) == 2

    def test_build_table_ambigu_meme_pid_deux_vids(self):
        """Un seul produit CJ mais le meme variantSku avec 2 vids ->
        AMBIGU (jamais de choix arbitraire)."""
        variants2 = {"code": 200, "result": True, "data": [
            {"vid": "1797521453454209024", "variantSku": "CJJT205244502BY"},
            {"vid": "3333333333333333333", "variantSku": "CJJT205244502BY"},
        ]}
        res = run(daily.build_vid_table(
            [{"fw_product_id": "18809643", "fw_variant_id": "WPPmLB",
              "variant_sku": "CJJT205244502BY"}],
            cj_search_fn=_async(CJ_SEARCH_REEL),
            cj_variants_fn=_async(variants2)))
        assert res["table"] == {}
        assert len(res["ambigus"]) == 1

    def test_build_table_aucune_donnee_personnelle(self):
        """SECURITE : la table ne contient que des identifiants metier
        (liste blanche EXACTE de cles, recursive)."""
        res = run(daily.build_vid_table(
            [{"fw_product_id": "18809643", "fw_product_sku": "SHP-CJT2052445",
              "fw_variant_id": "WPPmLB", "variant_sku": "CJJT205244502BY"}],
            cj_search_fn=_async(CJ_SEARCH_REEL),
            cj_variants_fn=_async({"code": 200, "result": True,
                                   "data": CJ_VARIANTES_ATTRAPE_REEL})))
        AUTORISES = {"table", "absents", "ambigus", "nb_variantes_fw",
                     "vid", "fw_product_id", "fw_product_sku",
                     "fw_variant_id", "variant_sku", "cj_pid",
                     "motif", "candidats_vid"}
        cles = set()

        def collecte(obj):
            if isinstance(obj, dict):
                cles.update(obj.keys())
                for v in obj.values():
                    collecte(v)
            elif isinstance(obj, list):
                for v in obj:
                    collecte(v)
        collecte(res)
        hors = cles - AUTORISES
        assert not hors, "cles hors liste blanche : " + repr(hors)
        blob = json.dumps(res).lower()
        for interdit in ("email", "telephone", "forename", "surname",
                         "address1", "anonyme", "0000000000"):
            assert interdit not in blob

    def test_seed_amorce_verifiee_reelle(self):
        """L'amorce contient EXACTEMENT les correspondances mesurees en
        lecture seule le 02/11/2026."""
        assert set(daily.VID_TABLE_SEED) == {"CJJT205244501AZ",
                                            "CJJT205244502BY"}
        assert daily.VID_TABLE_SEED["CJJT205244501AZ"]["vid"] == "1797521453382905856"
        assert daily.VID_TABLE_SEED["CJJT205244502BY"]["vid"] == "1797521453454209024"
        assert daily.VID_TABLE_SEED["CJJT205244502BY"]["fw_variant_id"] == "WPPmLB"
        for e in daily.VID_TABLE_SEED.values():
            assert set(e) == {"vid", "fw_product_id", "fw_variant_id", "cj_pid"}

    def _process_mocks(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            if request.url.path.endswith("/logistic/freight/calculate"):
                return httpx.Response(200, json={
                    "code": 200, "result": True, "data": [
                        {"logisticName": "CJStandard", "logisticPrice": "4.69",
                         "logisticAging": "4-10"}]})
            raise AssertionError("endpoint inattendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        monkeypatch.setenv("CJ_API_KEY", "test-key")

    def test_process_order_resout_vid_via_table(self, monkeypatch):
        """Pipeline REEL complet : panier FR (SKU Noir CJJT205244502BY)
        -> vid resolu par la table -> fret CJ calcule -> ligne verifiee.
        postage reel 0.00 EUR -> alerte marge non couverte (attendu)."""
        self._process_mocks(monkeypatch)
        vid_table = {"table": {"CJJT205244502BY": {
            "vid": "1797521453454209024",
            "fw_product_id": "18809643",
            "fw_variant_id": "WPPmLB",
            "cj_pid": "1797521453303214080"}}, "absents": [], "ambigus": []}
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        rep = run(daily.process_order(norm, vid_table=vid_table))
        ligne = rep["lignes"][0]
        assert ligne["statut"] == "verifie"
        assert ligne["vid"] == "1797521453454209024"
        assert ligne["vid_source"] == "table_sku_vid"
        assert ligne["fret_cj_eur"] == round(4.69 * 0.895, 2)
        assert rep["statut"] != "lignes_non_verifiees"
        # postage reel = 0.00 EUR : marge non couverte -> alerte
        assert any("non couverte" in a for a in rep["alertes"])

    def test_process_order_vid_table_tarif_couvert(self, monkeypatch):
        """Avec un tarif de livraison facture couvrant le fret reel :
        commande verifiee sans alerte."""
        self._process_mocks(monkeypatch)
        vid_table = {"table": {"CJJT205244502BY": {
            "vid": "1797521453454209024",
            "fw_product_id": "18809643",
            "fw_variant_id": "WPPmLB",
            "cj_pid": "1797521453303214080"}}, "absents": [], "ambigus": []}
        order = {"id": "ORD-1", "country": "FR", "shipping_charged": 6.0,
                 "items": [{"vid": None, "sku": "CJJT205244502BY",
                            "quantity": 1}]}
        rep = run(daily.process_order(order, vid_table=vid_table))
        assert rep["lignes"][0]["statut"] == "verifie"
        assert rep["statut"] == "verifie"
        assert rep["alertes"] == []

    def test_process_order_sku_ambigu_reste_sans_vid(self, monkeypatch):
        """SKU ambigu dans la table : sans_vid CONSERVE + alerte AMBIGUE,
        aucun appel CJ emis."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            raise AssertionError("aucun appel CJ attendu : " + request.url.path)

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        vid_table = {"table": {}, "absents": [], "ambigus": [
            {"variant_sku": "CJJT205244502BY",
             "candidats_vid": ["111", "222"],
             "motif": "SKU correspond a plusieurs vids CJ"}]}
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        rep = run(daily.process_order(norm, vid_table=vid_table))
        ligne = rep["lignes"][0]
        assert ligne["statut"] == "sans_vid"
        assert ligne["vid"] is None
        assert "AMBIGUE" in ligne["alerte"]
        assert rep["statut"] == "lignes_non_verifiees"

    def test_process_order_sku_absent_reste_sans_vid(self, monkeypatch):
        """SKU absent de la table : comportement v5.2 conserve."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            raise AssertionError("aucun appel CJ attendu")

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        vid_table = {"table": {}, "absents": [], "ambigus": []}
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        rep = run(daily.process_order(norm, vid_table=vid_table))
        ligne = rep["lignes"][0]
        assert ligne["statut"] == "sans_vid"
        assert "correspondance SKU->vid requise" in ligne["alerte"]
        assert rep["statut"] == "lignes_non_verifiees"

    def test_process_order_sans_table_comportement_v52(self, monkeypatch):
        """Sans vid_table : comportement v5.2 strictement inchange."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.frankfurter.app":
                return httpx.Response(200, json={"rates": {"EUR": 0.895}})
            raise AssertionError("aucun appel CJ attendu")

        class Patched(httpx.AsyncClient):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        norm = daily.fw_normalize_order(FW_PANIER_REEL_FR)
        rep = run(daily.process_order(norm))
        assert rep["lignes"][0]["statut"] == "sans_vid"

    def test_protection_vid_table_lecture_seule(self):
        """build_vid_table : aucun endpoint d'ordre fournisseur ni
        d'ecriture ; allow_publish par defaut False INCHANGE."""
        import inspect
        src_build = inspect.getsource(daily.build_vid_table)
        for interdit in ("shopping/order", "purchase", "createOrder",
                         "cancelOrder", "payOrder", "fw_create"):
            assert interdit not in src_build, interdit
        p = daily.DailyParams()
        assert p.allow_publish is False
