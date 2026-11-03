"""Gestionnaire fournisseurs : API, import CSV et qualification commerciale.

Les fournisseurs peuvent être établis dans n'importe quel pays ISO.
Les imports manuels/CSV sont des pistes à vérifier, pas des offres
automatiquement vendables. Une publication exige la qualification
complète dans supplier_qualification.py pour chaque destination/quantité.
"""
import csv
import io
import math

from intl import CURRENCIES, get_country


COLONNES_CSV = (
    "nom_fournisseur", "sku", "nom_produit", "prix_achat",
    "devise", "stock", "pays_expedition", "delai_jours",
)


class EnregistrementFournisseur:
    def __init__(self, nom, sku, produit, prix_achat, devise, stock,
                 pays_expedition, delai_jours, origine):
        self.nom = str(nom).strip()
        self.sku = str(sku).strip()
        self.produit = str(produit).strip()
        self.prix_achat = float(prix_achat)
        self.devise = str(devise).strip().upper()
        self.stock = int(stock)
        self.pays_expedition = str(pays_expedition).strip().upper()
        self.delai_jours = int(delai_jours)
        self.origine = origine
        # L'enregistrement n'est jamais considéré comme une preuve de
        # stock, d'identité ou de conformité produit.
        self.verifie = False
        self.vendable = False

    def en_dict(self):
        return dict(
            nom=self.nom, sku=self.sku, produit=self.produit,
            prix_achat=self.prix_achat, devise=self.devise,
            stock=self.stock, pays_expedition=self.pays_expedition,
            delai_jours=self.delai_jours, origine=self.origine,
            verifie=self.verifie, vendable=self.vendable,
        )


class GestionnaireFournisseurs:
    def __init__(self, registre):
        self.registre = registre
        self._catalogue = []

    @staticmethod
    def _valider_champs(nom, sku, produit, prix_achat, devise, stock,
                        pays_expedition, delai_jours):
        if not all(str(value or "").strip() for value in (nom, sku, produit)):
            raise ValueError("nom fournisseur, SKU et nom produit obligatoires")
        try:
            price = float(prix_achat)
        except (TypeError, ValueError) as exc:
            raise ValueError("prix achat invalide") from exc
        if not math.isfinite(price) or price <= 0:
            raise ValueError("prix achat non positif ou non fini")
        currency = str(devise).strip().upper()
        if currency not in CURRENCIES:
            raise ValueError("devise ISO 4217 non prise en charge")
        if not isinstance(stock, int) or isinstance(stock, bool):
            try:
                stock = int(stock)
            except (TypeError, ValueError) as exc:
                raise ValueError("stock entier invalide") from exc
        if stock < 0:
            raise ValueError("stock négatif interdit")
        country = str(pays_expedition or "").strip().upper()
        try:
            get_country(country)
        except KeyError as exc:
            raise ValueError("pays expédition ISO 3166-1 inconnu") from exc
        try:
            days = int(delai_jours)
        except (TypeError, ValueError) as exc:
            raise ValueError("délai invalide") from exc
        if days < 0:
            raise ValueError("délai négatif interdit")
        return price, currency, stock, country, days

    def importer_csv(self, contenu_csv):
        """Import CSV strict et tracé.

        Les champs saisis ne sont jamais interprétés comme devis réel,
        contrôle de conformité, stock vérifié ou autorisation de vente.
        """
        ajoutes, refuses = [], []
        lecteur = csv.DictReader(io.StringIO(contenu_csv))
        if tuple(lecteur.fieldnames or ()) != COLONNES_CSV:
            raise ValueError("en-tête CSV invalide : attendu " + ",".join(COLONNES_CSV))
        for numero, ligne in enumerate(lecteur, start=2):
            try:
                price, currency, stock, origin, days = self._valider_champs(
                    ligne["nom_fournisseur"], ligne["sku"], ligne["nom_produit"],
                    ligne["prix_achat"], ligne["devise"], ligne["stock"],
                    ligne["pays_expedition"], ligne["delai_jours"],
                )
                record = EnregistrementFournisseur(
                    ligne["nom_fournisseur"], ligne["sku"], ligne["nom_produit"],
                    price, currency, stock, origin, days, "csv",
                )
                self._catalogue.append(record)
                ajoutes.append(numero)
            except (ValueError, TypeError, KeyError):
                refuses.append(numero)
        return {"ajoutes": ajoutes, "refuses": refuses}

    def saisie_manuelle(self, **champs):
        """Saisie contrôlée ; l'origine peut être n'importe quel code ISO."""
        manquants = [
            field for field in COLONNES_CSV
            if field not in champs or champs[field] is None
            or (isinstance(champs[field], str) and not champs[field].strip())
        ]
        if manquants:
            raise ValueError("champs manquants: " + ", ".join(manquants))
        price, currency, stock, origin, days = self._valider_champs(
            champs["nom_fournisseur"], champs["sku"], champs["nom_produit"],
            champs["prix_achat"], champs["devise"], champs["stock"],
            champs["pays_expedition"], champs["delai_jours"],
        )
        record = EnregistrementFournisseur(
            champs["nom_fournisseur"], champs["sku"], champs["nom_produit"],
            price, currency, stock, origin, days, "saisie_manuelle",
        )
        self._catalogue.append(record)
        return record

    def catalogue(self):
        return [record.en_dict() for record in self._catalogue]

    def provenance(self):
        counts = {}
        for record in self._catalogue:
            counts[record.origine] = counts.get(record.origine, 0) + 1
        return counts

    def evaluer_offre(self, offre, destination, quantite,
                      taux_vers_eur, maintenant=None):
        """Applique les règles de la boutique à une offre et un marché."""
        from shoplinous_global.supplier_qualification import evaluer_offre
        return evaluer_offre(
            offre, destination, quantite, taux_vers_eur, maintenant
        )

    def evaluer_offres(self, offres, destination, quantite,
                       taux_vers_eur, maintenant=None):
        """Compare toutes les offres mondiales, puis écarte les non conformes."""
        from shoplinous_global.supplier_qualification import evaluer_offres
        return evaluer_offres(
            offres, destination, quantite, taux_vers_eur, maintenant
        )

    def meilleure_offre(self, offres, destination, quantite,
                        taux_vers_eur, maintenant=None):
        """Renvoie la meilleure offre conforme, ou None si aucune ne passe."""
        result = self.evaluer_offres(
            offres, destination, quantite, taux_vers_eur, maintenant
        )
        return result["meilleure_offre"]

    def rechercher_et_qualifier(self, mot_cle, destination, quantite,
                                taux_vers_eur, maintenant=None):
        """Recherche tous les fournisseurs API actifs, puis qualifie leurs offres.

        Les connecteurs sans API active sont ignorés et signalés. Les offres
        récupérées sont contrôlées avec exactement les mêmes règles,
        indépendamment du pays d'origine du fournisseur ou de l'entrepôt.
        """
        if not hasattr(self.registre, "rechercher_offres"):
            raise RuntimeError("registre sans recherche mondiale normalisée")
        discovery = self.registre.rechercher_offres(
            mot_cle, destination, quantite
        )
        result = self.evaluer_offres(
            discovery["offres"], destination, quantite,
            taux_vers_eur, maintenant
        )
        result["erreurs_connecteurs"] = discovery["erreurs"]
        result["adaptateurs_sans_recherche"] = discovery[
            "adaptateurs_sans_recherche"
        ]
        result["fournisseurs_interroges"] = sorted({
            item["fournisseur"] for item in discovery["offres"]
        })
        return result
