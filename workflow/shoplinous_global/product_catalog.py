"""Product Catalog Manager : catalogue multi-fournisseurs.

Regroupe les produits sans toucher a Freewebstore : la publication
reste la responsabilite du workflow existant (daily.py,
fw_create_product) et reste soumise a autorisation explicite.
"""

class CatalogueProduits:
    def __init__(self):
        self._produits = {}

    def ajouter(self, produit):
        ref = (produit or {}).get("reference_unique")
        if not ref:
            raise ValueError("reference_unique obligatoire")
        if ref in self._produits:
            raise ValueError("doublon de reference: " + repr(ref))
        self._produits[ref] = dict(produit)
        return ref

    def obtenir(self, ref):
        if ref not in self._produits:
            raise KeyError("produit inconnu: " + repr(ref))
        return dict(self._produits[ref])

    def par_fournisseur(self, nom):
        return {r: dict(p) for r, p in self._produits.items()
                if p.get("fournisseur") == nom}

    def lister(self):
        return {r: dict(p) for r, p in self._produits.items()}
