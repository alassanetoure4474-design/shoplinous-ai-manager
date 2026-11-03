"""Tests offline de l'adaptateur CJ normalisé (aucun appel réseau ni achat)."""
import asyncio
import json
import re
import time
import types
import sys

import pytest

from shoplinous_global import supplier_adapters
from shoplinous_global import supplier_manager
from shoplinous_global.exchange_rate_manager import TauxHorodate


def fake_daily():
    calls = {"freight": [], "stock": 0, "images": []}

    async def cj_search(keyword):
        assert keyword == "home organizer"
        return {
            "code": 200,
            "data": {"content": [{
                "productList": [{
                    "id": "product-1",
                    "sku": "PRODUCT-1",
                    "nameEn": "Foldable Home Organizer",
                    "bigImage": "https://images.example.test/main.jpg",
                }]
            }]},
        }

    async def cj_variants(pid):
        assert pid == "product-1"
        return {"code": 200, "data": [{
            "vid": "variant-1",
            "variantSku": "VARIANT-1",
            "variantSellPrice": "2.50",
            "variantImage": "https://images.example.test/variant.jpg",
        }]}

    async def cj_product_detail(pid):
        assert pid == "product-1"
        return {"code": 200, "data": [{
            "productImage": json.dumps([
                "https://images.example.test/gallery-1.jpg",
                "https://images.example.test/gallery-2.jpg",
            ])
        }]}

    def parse_cj_images(payload):
        raw = payload["data"][0]["productImage"]
        return json.loads(raw)

    def cn_stock_of(payload):
        for entry in payload.get("data", []):
            if entry.get("countryCode") == "CN":
                return int(entry.get("storageNum") or entry.get("totalInventoryNum") or 0)
        return 0

    async def cj_stock(vid):
        assert vid == "variant-1"
        calls["stock"] += 1
        return {"code": 200, "data": [{
            "countryCode": "CN",
            "storageNum": 1500,
            "totalInventoryNum": 1500,
        }]}

    async def cj_freight(vid, country, quantity):
        calls["freight"].append((vid, country, quantity))
        return {"code": 200, "data": [{
            "logisticName": "Test Line",
            "logisticPrice": "3.00",
            "logisticAging": "5-8",
        }]}

    async def check_image(url):
        calls["images"].append(url)
        return {"url": url, "bytes": 8192, "mime": "image/jpeg"}

    fake = types.SimpleNamespace(
        BANNED_PATTERNS=re.compile(
            r"(?i)\b(battery|bluetooth|drone|knife|weapon)\b"
        ),
        cj_search=cj_search,
        cj_variants=cj_variants,
        cj_product_detail=cj_product_detail,
        cj_stock=cj_stock,
        cj_freight=cj_freight,
        parse_cj_images=parse_cj_images,
        cn_stock_of=cn_stock_of,
        check_image=check_image,
    )
    return fake, calls


def install_fake_daily(monkeypatch):
    fake, calls = fake_daily()
    monkeypatch.setenv("CJ_API_KEY", "test-key-not-used-by-fake")
    monkeypatch.setitem(sys.modules, "daily", fake)
    return calls


def test_cj_adapter_returns_live_normalized_offer_for_exact_destination_and_qty(
    monkeypatch,
):
    calls = install_fake_daily(monkeypatch)
    registry = supplier_adapters.RegistreFournisseurs()

    result = registry.rechercher_offres("home organizer", "FR", 3)

    assert result["erreurs"] == []
    assert result["adaptateurs_sans_recherche"] == []
    assert len(result["offres"]) == 1
    offer = result["offres"][0]
    assert offer["fournisseur"] == "cj"  # injecté par le registre
    assert offer["pays_fournisseur"] == "CN"
    assert offer["pays_entrepot"] == "CN"
    assert offer["sku"] == "VARIANT-1"
    assert offer["prix_achat"] == "2.50"
    assert offer["devise_achat"] == "USD"
    assert offer["stock"] == 1500
    assert offer["stock_verifie"] is True
    assert offer["images_validees"] == 2
    assert len(offer["images_urls_verifiees"]) == 2
    assert offer["fournisseur_verifie"] is True
    assert offer["conformite_verifiee"] is False
    quote = offer["devis_livraison"]
    assert quote["verifie"] is True
    assert quote["destination"] == "FR"
    assert quote["quantite"] == 3
    assert quote["cout"] == 3.0
    assert quote["devise"] == "USD"
    assert quote["delai_min_jours"] == 5
    assert quote["delai_max_jours"] == 8
    assert quote["restrictions_ok"] is False
    assert quote["expire_le"] > quote["verifie_le"]
    assert calls["freight"] == [("variant-1", "FR", 3)]
    assert calls["stock"] == 1
    assert len(calls["images"]) == 2


def test_global_manager_keeps_cj_offer_blocked_without_compliance_and_customs_proof(
    monkeypatch,
):
    install_fake_daily(monkeypatch)
    registry = supplier_adapters.RegistreFournisseurs()
    manager = supplier_manager.GestionnaireFournisseurs(registry)
    now = time.time()
    rates = {
        "USD": TauxHorodate(("USD", "EUR"), 0.92, horodatage=now - 5)
    }

    report = manager.rechercher_et_qualifier(
        "home organizer", "FR", 3, rates, maintenant=now
    )

    assert report["nombre_offres"] == 1
    assert report["nombre_conformes"] == 0
    assert report["meilleure_offre"] is None
    assert report["fournisseurs_interroges"] == ["cj"]
    refusal = report["offres_refusees"][0]["refus"]
    assert "conformité produit non vérifiée ou preuve absente" in refusal
    assert "restrictions douanières ou d'importation non levées" in refusal


def test_cj_adapter_requires_sync_entrypoint_outside_running_event_loop():
    adapter = supplier_adapters.AdaptateurCJ()

    async def invoke():
        with pytest.raises(RuntimeError, match="boucle asyncio active"):
            adapter.rechercher_offres("home organizer", "FR", 1)

    asyncio.run(invoke())


def test_cj_adapter_rejects_invalid_quantity_before_any_api_call(monkeypatch):
    calls = install_fake_daily(monkeypatch)
    adapter = supplier_adapters.AdaptateurCJ()

    with pytest.raises(ValueError, match="quantité entière positive"):
        adapter.rechercher_offres("home organizer", "FR", 0)

    assert calls["stock"] == 0
    assert calls["freight"] == []



def test_cj_adapter_async_entrypoint_works_inside_workflow_event_loop(monkeypatch):
    install_fake_daily(monkeypatch)
    registry = supplier_adapters.RegistreFournisseurs()

    async def invoke():
        result = await registry.rechercher_offres_async(
            "home organizer", "FR", 2
        )
        assert result["erreurs"] == []
        assert len(result["offres"]) == 1
        assert result["offres"][0]["devis_livraison"]["quantite"] == 2

    asyncio.run(invoke())


def test_supplier_manager_async_path_keeps_unverified_offer_blocked(monkeypatch):
    install_fake_daily(monkeypatch)
    registry = supplier_adapters.RegistreFournisseurs()
    manager = supplier_manager.GestionnaireFournisseurs(registry)
    now = time.time()
    rates = {
        "USD": TauxHorodate(("USD", "EUR"), 0.92, horodatage=now - 5)
    }

    async def invoke():
        report = await manager.rechercher_et_qualifier_async(
            "home organizer", "FR", 2, rates, maintenant=now
        )
        assert report["nombre_offres"] == 1
        assert report["nombre_conformes"] == 0
        assert report["meilleure_offre"] is None
        assert report["fournisseurs_interroges"] == ["cj"]

    asyncio.run(invoke())
