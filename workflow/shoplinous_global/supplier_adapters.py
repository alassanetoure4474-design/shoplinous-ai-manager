"""Registre mondial d'adaptateurs fournisseurs.

L'origine du fournisseur ou de l'entrepôt n'est pas une liste blanche :
un adaptateur connecté peut proposer une offre vers n'importe quelle
destination, sous réserve du devis réel et de la qualification SHOPLINOUS.
Les intégrations non connectées restent explicitement inactives.
"""
import re


class AdaptateurFournisseur:
    nom = "base"
    connected = False
    capacites = ()
    pays_expedition = ()

    def methodes(self):
        return {capability: getattr(self, capability, None)
                for capability in self.capacites}


class AdaptateurCJ(AdaptateurFournisseur):
    """Délègue aux outils CJ réels de daily.py, sans achat automatique."""
    nom = "cj"
    connected = True
    capacites = ("produits_recherche", "variantes", "detail", "stock", "fret")
    pays_expedition = ("CN",)

    def produits_recherche(self, mot_cle):
        import asyncio
        import daily
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(daily.cj_search(mot_cle))
        finally:
            loop.close()

    def variantes(self, pid):
        import asyncio
        import daily
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(daily.cj_variants(pid))
        finally:
            loop.close()

    def detail(self, pid):
        import asyncio
        import daily
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(daily.cj_product_detail(pid))
        finally:
            loop.close()

    def stock(self, vid):
        import asyncio
        import daily
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(daily.cj_stock(vid))
        finally:
            loop.close()

    def fret(self, vid, pays, quantite):
        import asyncio
        import daily
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(daily.cj_freight(vid, pays, quantite))
        finally:
            loop.close()


class AdaptateurNonConnecte(AdaptateurFournisseur):
    """Fournisseur répertorié, mais sans API ni contrat actif."""

    def __init__(self, nom, pays_expedition=()):
        self.nom = nom
        self.pays_expedition = tuple(pays_expedition)
        self.capacites = (
            "produits_recherche", "variantes", "detail", "stock", "fret", "suivi"
        )

    def methodes(self):
        return {capability: None for capability in self.capacites}


class RegistreFournisseurs:
    def __init__(self, adaptateurs=None):
        cj = AdaptateurCJ()
        self._fournisseurs = {cj.nom: cj}
        # Noms prévus, sans prétendre que leurs API/contrats sont actifs.
        for name, origins in (
            ("aliexpress", ("CN",)),
            ("bigbuy", ("ES", "IT")),
            ("spocket", ("US", "EU")),
            ("printful", ("US", "LV")),
            ("fournisseurs_africains", ("CI", "SN", "NG")),
            ("fournisseurs_ivoiriens", ("CI",)),
            ("personnalise", ()),
        ):
            self._fournisseurs[name] = AdaptateurNonConnecte(name, origins)
        for adapter in adaptateurs or ():
            self.enregistrer(adapter)

    def enregistrer(self, adaptateur, remplacer=False):
        """Enregistre un vrai adaptateur API ou un fournisseur personnalisé.

        pays_expedition est une indication de provenance, jamais une règle
        d'exclusion des destinations. L'état connected doit rester False
        tant que l'authentification et les appels réels ne sont pas testés.
        """
        name = str(getattr(adaptateur, "nom", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", name):
            raise ValueError("nom adaptateur invalide")
        if not isinstance(getattr(adaptateur, "connected", None), bool):
            raise ValueError("connected doit être un booléen explicite")
        capabilities = getattr(adaptateur, "capacites", ())
        if not isinstance(capabilities, (tuple, list)) or not capabilities:
            raise ValueError("capacités adaptateur manquantes")
        origins = getattr(adaptateur, "pays_expedition", ())
        if not isinstance(origins, (tuple, list, set)):
            raise ValueError("pays_expedition doit être une collection")
        if name in self._fournisseurs and not remplacer:
            raise ValueError("fournisseur déjà enregistré : " + name)
        self._fournisseurs[name] = adaptateur
        return name

    def tous(self):
        return dict(self._fournisseurs)

    def connectes(self):
        return {
            name: adapter for name, adapter in self._fournisseurs.items()
            if adapter.connected is True
        }

    def pour_pays(self, code_pays):
        """Retourne les adaptateurs actifs pour la destination demandée.

        Le pays d'expédition n'est volontairement pas comparé à code_pays.
        Seul l'état de connexion compte ici ; chaque offre doit ensuite
        fournir un devis réel et réussir supplier_qualification.
        """
        from intl import get_country
        get_country(code_pays)
        return sorted(self.connectes())

    def par_origine(self, code_origine):
        """Filtre informatif par origine, sans limiter la destination."""
        from intl import get_country
        code = str(code_origine).strip().upper()
        get_country(code)
        return sorted(
            name for name, adapter in self._fournisseurs.items()
            if adapter.connected is True
            and (code in tuple(getattr(adapter, "pays_expedition", ()))
                 or "*" in tuple(getattr(adapter, "pays_expedition", ())))
        )

    def etat(self):
        return {
            name: {
                "connecte": adapter.connected is True,
                "pays_expedition": list(adapter.pays_expedition),
                "capacites": list(adapter.capacites),
                "candidature_mondiale": adapter.connected is True,
            }
            for name, adapter in self._fournisseurs.items()
        }
