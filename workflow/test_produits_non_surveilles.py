"""Tests v5.9 : detection des produits FW non couverts par catalog_watch.

PROBLEME REEL (constate en lecture seule le 03/11/2026) : les produits
FW crees SANS variants[] (SPL-COINBOX-EUR 64593185, SPL-PRESSE-AIL-1
73715777) ne produisent AUCUN fw_variant_record -> absents de la
vid_table -> jamais revalides par catalog_watch (angle mort).

La correction v5.9 est un MOTEUR PUR en lecture seule : elle SIGNALE
ces produits (alerte "produit_non_surveille") sans rien ecrire et sans
inventer d'association. Tests unitaires uniquement, aucun reseau.
"""

from workflow.daily import detecter_produits_non_surveilles


def _table(sku):
    return {"table": {sku: {"vid": "v1", "fw_product_id": "1",
                            "fw_variant_id": "u1", "cj_pid": "p1"}}}


def test_produit_sans_variante_detecte():
    catalogue = [{"id": 64593185, "sku": "SPL-COINBOX-EUR", "name": "Box"}]
    resultat = detecter_produits_non_surveilles(catalogue, [], {"table": {}})
    assert len(resultat) == 1
    assert resultat[0]["fw_product_id"] == "64593185"
    assert resultat[0]["motif"] == "produit sans variante FW"
    assert resultat[0]["nb_variantes_fw"] == 0


def test_produit_avec_sku_sans_correspondance_detecte():
    catalogue = [{"id": 1, "sku": "A", "name": "A"}]
    fw_records = [{"fw_product_id": "1", "variant_sku": "SKU-ORPHELIN"}]
    resultat = detecter_produits_non_surveilles(catalogue, fw_records, {"table": {}})
    assert len(resultat) == 1
    assert resultat[0]["motif"].startswith("aucune variante associee")


def test_produit_surveille_non_detecte():
    catalogue = [{"id": 1, "sku": "A", "name": "A"}]
    fw_records = [{"fw_product_id": "1", "variant_sku": "SKU-OK"}]
    resultat = detecter_produits_non_surveilles(catalogue, fw_records, _table("SKU-OK"))
    assert resultat == []


def test_melange_surveille_et_orphelin():
    catalogue = [{"id": 1, "sku": "A", "name": "A"},
                 {"id": 2, "sku": "B", "name": "B"},
                 {"id": 3, "sku": "C", "name": "C"}]
    fw_records = [{"fw_product_id": "1", "variant_sku": "SKU-OK"},
                   {"fw_product_id": "2", "variant_sku": "SKU-ORPHELIN"}]
    resultat = detecter_produits_non_surveilles(catalogue, fw_records, _table("SKU-OK"))
    ids = sorted(r["fw_product_id"] for r in resultat)
    assert ids == ["2", "3"]


def test_entrees_mal_formees_sans_crash():
    catalogue = [None, {}, {"id": 7, "sku": "X"}, 42]
    fw_records = [None, {"fw_product_id": None}, 3,
                  {"fw_product_id": "7", "variant_sku": "S"}]
    resultat = detecter_produits_non_surveilles(catalogue, fw_records, {"table": {}})
    assert len(resultat) == 1
    assert resultat[0]["fw_product_id"] == "7"


def test_aucune_association_inventee():
    """Un produit sans variante n'est JAMAIS associe approximativement :
    il est seulement signale (fail-closed, resolution manuelle)."""
    catalogue = [{"id": 9, "sku": "SPL-PRESSE-AIL-1", "name": "Presse"}]
    fw_records = [{"fw_product_id": "1", "variant_sku": "SKU-AUTRE"}]
    resultat = detecter_produits_non_surveilles(catalogue, fw_records,
                                                _table("SKU-AUTRE"))
    assert len(resultat) == 1
    assert "fw_variant_id" not in resultat[0]


def test_cas_reel_boutique_03112026():
    """Cas reel simplifie : 6 produits publies, 2 sans variante ->
    exactement 2 non surveilles, 4 couverts."""
    catalogue = [{"id": 18809643, "sku": "SHP-A", "name": "A"},
                 {"id": 58400689, "sku": "SHP-B", "name": "B"},
                 {"id": 76644587, "sku": "SHP-C", "name": "C"},
                 {"id": 84438429, "sku": "SHP-D", "name": "D"},
                 {"id": 64593185, "sku": "SPL-COINBOX-EUR", "name": "E"},
                 {"id": 73715777, "sku": "SPL-PRESSE-AIL-1", "name": "F"}]
    fw_records = [{"fw_product_id": "18809643", "variant_sku": "SK1"},
                   {"fw_product_id": "58400689", "variant_sku": "SK2"},
                   {"fw_product_id": "76644587", "variant_sku": "SK3"},
                   {"fw_product_id": "84438429", "variant_sku": "SK4"}]
    table = {"table": {s: {"vid": s, "fw_product_id": "1",
                          "fw_variant_id": "u", "cj_pid": "p"}
              for s in ("SK1", "SK2", "SK3", "SK4")}}
    resultat = detecter_produits_non_surveilles(catalogue, fw_records, table)
    assert sorted(r["fw_product_sku"] for r in resultat) == \
        ["SPL-COINBOX-EUR", "SPL-PRESSE-AIL-1"]