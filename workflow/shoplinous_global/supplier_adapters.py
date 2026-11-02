"""Supplier Adapter Registry : adaptateurs fournisseurs.

CJdropshipping = integration REELLE existante (deleguee aux outils
daily.py). Tous les autres fournisseurs (AliExpress, BigBuy, Spocket,
Printful, fournisseurs africains/ivoiriens, personnalises) sont
registres NON CONNECTES : aucun appel n est simule.
"""

class AdaptateurFournisseur:
    nom = "base"
    connected = False
    capacites = ()
    pays_expedition = ()

    def methodes(self):
        return {c: getattr(self, c, None) for c in self.capacites}


class AdaptateurCJ(AdaptateurFournisseur):
    """Delegue aux fonctions REELLES de daily.py (outils cj_search,
    cj_variants, cj_product_detail, cj_stock, cj_freight) sans les
    modifier. Les commandes restent interdites sans autorisation."""
    nom = "cj"
    connected = True
    capacites = ("produits_recherche", "variantes", "detail", "stock",
                 "fret")
    pays_expedition = ("CN",)

    def produits_recherche(self, mot_cle):
        import asyncio, daily
        return asyncio.get_event_loop_policy().new_event_loop(
        ).run_until_complete(daily.cj_search(mot_cle))

    def variantes(self, pid):
        import asyncio, daily
        return asyncio.get_event_loop_policy().new_event_loop(
        ).run_until_complete(daily.cj_variants(pid))

    def detail(self, pid):
        import asyncio, daily
        return asyncio.get_event_loop_policy().new_event_loop(
        ).run_until_complete(daily.cj_product_detail(pid))

    def stock(self, vid):
        import asyncio, daily
        return asyncio.get_event_loop_policy().new_event_loop(
        ).run_until_complete(daily.cj_stock(vid))

    def fret(self, vid, pays, quantite):
        import asyncio, daily
        return asyncio.get_event_loop_policy().new_event_loop(
        ).run_until_complete(daily.cj_freight(vid, pays, quantite))


class AdaptateurNonConnecte(AdaptateurFournisseur):
    """Modele des fournisseurs prevus mais non contractes."""
    def __init__(self, nom, pays_expedition=()):
        self.nom = nom
        self.pays_expedition = tuple(pays_expedition)

    def methodes(self):
        return {c: None for c in self.capacites}


class RegistreFournisseurs:
    def __init__(self):
        cj = AdaptateurCJ()
        self._fournisseurs = {cj.nom: cj}
        for nom, pays in (
                ("aliexpress", ("CN",)), ("bigbuy", ("ES", "IT")),
                ("spocket", ("US", "EU")), ("printful", ("US", "LV")),
                ("fournisseurs_africains", ("CI", "SN", "NG")),
                ("fournisseurs_ivoiriens", ("CI",)),
                ("personnalise", ())):
            a = AdaptateurNonConnecte(nom, pays)
            a.capacites = ("produits_recherche", "variantes", "detail",
                           "stock", "fret", "suivi")
            self._fournisseurs[nom] = a

    def tous(self):
        return dict(self._fournisseurs)

    def connectes(self):
        return {n: a for n, a in self._fournisseurs.items()
                if a.connected}

    def pour_pays(self, code_pays):
        """Fournisseurs ACCESSIBLES pour un pays : connectes, ou
        declares dans la configuration du pays."""
        from shoplinous_global from shoplinous_global import country_manager
        conf = country_manager.pays(code_pays)
        return [n for n in self._fournisseurs
                if n in conf["fournisseurs"] or
                self._fournisseurs[n].connected]

    def etat(self):
        return {n: {"connecte": a.connected,
                    "pays_expedition": list(a.pays_expedition),
                    "capacites": list(a.capacites)}
                for n, a in self._fournisseurs.items()}
