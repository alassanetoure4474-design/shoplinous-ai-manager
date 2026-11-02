"""Tests de l'integration redaction produit FreeLLMAPI."""
import asyncio

import pytest

import daily


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_description_ia_utilise_le_texte_retourne(monkeypatch):
    async def fake_appeler_ia(messages):
        assert messages[0]["role"] == "system"
        assert "Nom fournisseur du produit" in messages[1]["content"]
        return {"contenu": "  Une jolie solution pour votre intérieur.  "}

    monkeypatch.setattr(daily.ai_manager, "appeler_ia", fake_appeler_ia)
    assert run(daily.ai_product_description("Wall decor")) == (
        "Une jolie solution pour votre intérieur.")


def test_description_ia_refuse_une_reponse_vide(monkeypatch):
    async def fake_appeler_ia(messages):
        return {"contenu": "   "}

    monkeypatch.setattr(daily.ai_manager, "appeler_ia", fake_appeler_ia)
    with pytest.raises(RuntimeError, match="vide"):
        run(daily.ai_product_description("Organizer"))


def test_description_ia_limitee_a_500_caracteres(monkeypatch):
    async def fake_appeler_ia(messages):
        return {"contenu": "x" * 700}

    monkeypatch.setattr(daily.ai_manager, "appeler_ia", fake_appeler_ia)
    assert len(run(daily.ai_product_description("Basket"))) == 500
