"""Adaptateur generique de catalogues fournisseurs CSV.

Normalise les flux fournisseurs sans les declarer vendables. Un CSV ne prouve
ni stock reel, ni identite, ni conformite, ni cout de livraison : la
qualification stricte reste obligatoire avant toute publication.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from intl import CURRENCIES, get_country

CHAMPS_CANONIQUES = (
    "sku", "nom_produit", "prix_achat", "devise",
    "stock_declare", "pays_entrepot",
)


class AdaptateurFluxCSV:
    nom = "flux_csv"
    connected = True
    capacites = ("import_catalogue_csv", "normaliser_offres")

    def __init__(self, nom_fournisseur, mapping, pays_fournisseur):
        self.nom_fournisseur = str(nom_fournisseur or "").strip()
        self.mapping = dict(mapping or {})
        self.pays_fournisseur = str(pays_fournisseur or "").strip().upper()
        if not self.nom_fournisseur:
            raise ValueError("nom fournisseur obligatoire")
        get_country(self.pays_fournisseur)
        missing = [field for field in CHAMPS_CANONIQUES if not self.mapping.get(field)]
        if missing:
            raise ValueError("mapping incomplet: " + ", ".join(missing))

    def importer(self, contenu, delimiter=","):
        if not isinstance(contenu, str) or not contenu.strip():
            raise ValueError("flux CSV vide")
        if delimiter not in (",", ";", "\t"):
            raise ValueError("separateur CSV non pris en charge")
        reader = csv.DictReader(io.StringIO(contenu), delimiter=delimiter)
        headers = set(reader.fieldnames or ())
        missing = sorted(set(self.mapping.values()) - headers)
        if missing:
            raise ValueError("colonnes CSV absentes: " + ", ".join(missing))
        offers, rejected = [], []
        for line_number, row in enumerate(reader, start=2):
            try:
                sku = str(row[self.mapping["sku"]] or "").strip()
                title = str(row[self.mapping["nom_produit"]] or "").strip()
                price = Decimal(str(row[self.mapping["prix_achat"]]).strip())
                currency = str(row[self.mapping["devise"]] or "").strip().upper()
                stock = int(str(row[self.mapping["stock_declare"]]).strip())
                origin = str(row[self.mapping["pays_entrepot"]] or "").strip().upper()
                if not sku or not title:
                    raise ValueError("SKU ou nom produit vide")
                if not price.is_finite() or price <= 0:
                    raise ValueError("prix achat invalide")
                if currency not in CURRENCIES:
                    raise ValueError("devise inconnue")
                if stock < 0:
                    raise ValueError("stock negatif")
                get_country(origin)
                offers.append({
                    "fournisseur": self.nom_fournisseur,
                    "pays_fournisseur": self.pays_fournisseur,
                    "pays_entrepot": origin,
                    "sku": sku,
                    "nom_produit": title,
                    "prix_achat": str(price),
                    "devise_achat": currency,
                    "stock_declare": stock,
                    "origine_donnee": "flux_csv_fournisseur",
                    "ligne_source": line_number,
                    "stock_verifie": False,
                    "fournisseur_verifie": False,
                    "conformite_verifiee": False,
                    "images_validees": 0,
                    "devis_livraison": None,
                    "eligible": False,
                })
            except (ValueError, TypeError, InvalidOperation, KeyError):
                rejected.append(line_number)
        return {
            "fournisseur": self.nom_fournisseur,
            "offres": offers,
            "lignes_refusees": rejected,
            "source_verifiee": False,
            "publication_autorisee": False,
        }
