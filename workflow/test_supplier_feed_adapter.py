"""Tests offline de l'adaptateur CSV fournisseur generique."""
import pytest
from shoplinous_global.supplier_feed_adapter import AdaptateurFluxCSV

MAPPING = {
    "sku": "Reference",
    "nom_produit": "Product",
    "prix_achat": "Wholesale price",
    "devise": "Currency",
    "stock_declare": "Available",
    "pays_entrepot": "Warehouse country",
}

def adapter():
    return AdaptateurFluxCSV("T.M. Textil", MAPPING, "DE")

def test_import_csv_normalizes_but_never_marks_offer_sellable():
    data = ("Reference,Product,Wholesale price,Currency,Available,Warehouse country\n"
            "TM-1,Home textile,4.20,EUR,1200,DE\n")
    result = adapter().importer(data)
    assert len(result["offres"]) == 1
    offer = result["offres"][0]
    assert offer["sku"] == "TM-1"
    assert offer["prix_achat"] == "4.20"
    assert offer["stock_declare"] == 1200
    assert offer["stock_verifie"] is False
    assert offer["fournisseur_verifie"] is False
    assert offer["conformite_verifiee"] is False
    assert offer["devis_livraison"] is None
    assert offer["eligible"] is False
    assert result["publication_autorisee"] is False

def test_import_csv_rejects_invalid_rows_without_dropping_valid_rows():
    data = ("Reference,Product,Wholesale price,Currency,Available,Warehouse country\n"
            "OK-1,Decor item,3.00,EUR,1000,DE\n"
            "BAD-1,Decor item,-2.00,EUR,1000,DE\n"
            "BAD-2,Decor item,3.00,XXX,1000,DE\n"
            "BAD-3,Decor item,3.00,EUR,-1,DE\n")
    result = adapter().importer(data)
    assert [x["sku"] for x in result["offres"]] == ["OK-1"]
    assert result["lignes_refusees"] == [3, 4, 5]

def test_import_csv_requires_mapped_columns():
    with pytest.raises(ValueError, match="colonnes CSV absentes"):
        adapter().importer("Reference,Product\nTM-1,Textile\n")

def test_mapping_requires_all_canonical_fields():
    with pytest.raises(ValueError, match="mapping incomplet"):
        AdaptateurFluxCSV("Supplier", {"sku": "SKU"}, "FR")

def test_unknown_supplier_country_is_rejected():
    with pytest.raises(KeyError):
        AdaptateurFluxCSV("Supplier", MAPPING, "ZZ")

def test_empty_feed_is_rejected():
    with pytest.raises(ValueError, match="vide"):
        adapter().importer("")
