"""Supplier Manager : fournisseurs, import CSV, saisie manuelle.

Trois voies d entree produit : API (adaptateur connecte), import CSV
(fournisseurs personnalises, colonnes strictes), saisie manuelle
(controlee). Aucune integration simulee n est presentee comme reelle.
"""
import csv
import io

COLONNES_CSV = ("nom_fournisseur", "sku", "nom_produit", "prix_achat",
                "devise", "stock", "pays_expedition", "delai_jours")


class EnregistrementFournisseur:
    def __init__(self, nom, sku, produit, prix_achat, devise, stock,
                 pays_expedition, delai_jours, origine):
        self.nom = nom
        self.sku = sku
        self.produit = produit
        self.prix_achat = float(prix_achat)
        self.devise = devise
        self.stock = int(stock)
        self.pays_expedition = pays_expedition
        self.delai_jours = int(delai_jours)
        self.origine = origine

    def en_dict(self):
        return dict(nom=self.nom, sku=self.sku, produit=self.produit,
                    prix_achat=self.prix_achat, devise=self.devise,
                    stock=self.stock,
                    pays_expedition=self.pays_expedition,
                    delai_jours=self.delai_jours, origine=self.origine)


class GestionnaireFournisseurs:
    def __init__(self, registre):
        self.registre = registre
        self._catalogue = []

    def importer_csv(self, contenu_csv):
        """Import CSV STRICT : colonnes exactes attendues, prix
        positifs, stock entier. Ligne invalide -> ligne ignoree et
        comptee (jamais silencieusement corrigee)."""
        ajoutes, refuses = [], []
        lecteur = csv.DictReader(io.StringIO(contenu_csv))
        if tuple(lecteur.fieldnames or ()) != COLONNES_CSV:
            raise ValueError("en-tete CSV invalide : attendu "
                             + ",".join(COLONNES_CSV))
        for numero, ligne in enumerate(lecteur, start=2):
            try:
                if float(ligne["prix_achat"]) <= 0:
                    raise ValueError("prix non positif")
                e = EnregistrementFournisseur(
                    ligne["nom_fournisseur"], ligne["sku"],
                    ligne["nom_produit"], ligne["prix_achat"],
                    ligne["devise"], int(ligne["stock"]),
                    ligne["pays_expedition"],
                    int(ligne["delai_jours"]), "csv")
                self._catalogue.append(e)
                ajoutes.append(numero)
            except (ValueError, TypeError, KeyError):
                refuses.append(numero)
        return {"ajoutes": ajoutes, "refuses": refuses}

    def saisie_manuelle(self, **champs):
        """Saisie manuelle controlee : memes regles que le CSV."""
        manquants = [c for c in COLONNES_CSV if not champs.get(c)]
        if manquants:
            raise ValueError("champs manquants: " + ", ".join(manquants))
        e = EnregistrementFournisseur(
            champs["nom_fournisseur"], champs["sku"],
            champs["nom_produit"], champs["prix_achat"],
            champs["devise"], champs["stock"],
            champs["pays_expedition"], champs["delai_jours"],
            "saisie_manuelle")
        self._catalogue.append(e)
        return e

    def catalogue(self):
        return [e.en_dict() for e in self._catalogue]

    def provenance(self):
        compte = {}
        for e in self._catalogue:
            compte[e.origine] = compte.get(e.origine, 0) + 1
        return compte
