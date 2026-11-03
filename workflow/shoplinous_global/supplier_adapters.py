"""Registre mondial d'adaptateurs fournisseurs.

L'origine du fournisseur ou de son entrepôt n'est pas une liste blanche :
un adaptateur connecté peut proposer une offre vers n'importe quelle
destination, sous réserve du devis réel et de la qualification SHOPLINOUS.
Les intégrations non connectées restent explicitement inactives.
"""
import asyncio
import math
import re
import time


class AdaptateurFournisseur:
    nom = "base"
    connected = False
    capacites = ()
    pays_expedition = ()

    def methodes(self):
        return {capability: getattr(self, capability, None)
                for capability in self.capacites}

    def rechercher_offres(self, mot_cle, destination, quantite):
        """Retourne des offres au format canonique du moteur de qualification.

        Un adaptateur concret doit appeler son API réelle et fournir les
        preuves de stock, images, identité, conformité et devis de transport.
        """
        raise NotImplementedError("recherche normalisée non implémentée")


class AdaptateurCJ(AdaptateurFournisseur):
    """Adaptateur CJ réel en lecture seule : catalogue, stock, images et fret.

    Les appels utilisent les activités CJ existantes de workflow/daily.py.
    Aucun endpoint de commande, d'achat, de paiement ou de publication n'est
    appelé ici. Les champs de conformité et de restrictions restent à False
    faute de justificatifs structurés fournis par les réponses CJ observées.
    """
    nom = "cj"
    connected = True
    capacites = (
        "produits_recherche", "variantes", "detail", "stock", "fret",
        "rechercher_offres",
    )
    pays_expedition = ("CN",)

    # Entité juridique indiquée dans les conditions officielles de CJ.
    PREUVE_IDENTITE = "https://cjdropshipping.com/user-agreement/en"
    FOURNISSEUR_LEGAL = "Yiwu Cujia Trade Co., Ltd."
    DEVISE_CJ = "USD"
    VALIDITE_INTERNE_DEVIS_SECONDES = 15 * 60

    @staticmethod
    def _executer(coroutine_factory, *args):
        """Exécute le lot CJ dans une boucle unique, sans boucle imbriquée."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine_factory(*args))
        raise RuntimeError(
            "rechercher_offres CJ est synchrone : appelez-le hors d'une "
            "boucle asyncio active"
        )

    def produits_recherche(self, mot_cle):
        import daily
        return self._executer(daily.cj_search, mot_cle)

    def variantes(self, pid):
        import daily
        return self._executer(daily.cj_variants, pid)

    def detail(self, pid):
        import daily
        return self._executer(daily.cj_product_detail, pid)

    def stock(self, vid):
        import daily
        return self._executer(daily.cj_stock, vid)

    def fret(self, vid, pays, quantite):
        import daily
        return self._executer(daily.cj_freight, vid, pays, quantite)

    def rechercher_offres(self, mot_cle, destination, quantite):
        import daily
        return self._executer(
            self._rechercher_offres_async, daily, mot_cle, destination, quantite
        )

    async def rechercher_offres_async(self, mot_cle, destination, quantite):
        """Point d'entrée asynchrone pour les workflows Mistral."""
        import daily
        return await self._rechercher_offres_async(
            daily, mot_cle, destination, quantite
        )

    async def _rechercher_offres_async(self, daily, mot_cle, destination, quantite):
        """Transforme les réponses CJ réelles en offres normalisées.

        L'entrepôt et le point de départ du devis sont CN, conformément aux
        requêtes CJ existantes (startCountryCode=CN) et au stock CN vérifié.
        La destination et la quantité sont toujours celles de l'appel.
        Une durée de validité de 15 minutes est une politique locale de fraîcheur
        SHOPLINOUS, pas une durée annoncée par CJ.
        """
        if not isinstance(mot_cle, str) or not mot_cle.strip():
            raise ValueError("mot-clé de recherche obligatoire")
        if not isinstance(destination, str) or len(destination.strip()) != 2:
            raise ValueError("destination ISO-2 obligatoire")
        destination = destination.strip().upper()
        if not isinstance(quantite, int) or isinstance(quantite, bool) or quantite < 1:
            raise ValueError("quantité entière positive obligatoire")

        search_payload = await daily.cj_search(mot_cle.strip())
        try:
            blocks = search_payload["data"]["content"]
            products = [
                product
                for block in blocks
                if isinstance(block, dict)
                for product in (block.get("productList") or [])
                if isinstance(product, dict) and product.get("id")
            ]
        except (KeyError, TypeError):
            raise RuntimeError("CJ search : structure productList inattendue")

        offers = []
        for product in products:
            product_id = str(product["id"])
            product_name = str(product.get("nameEn") or "").strip()
            if not product_name:
                continue
            if daily.BANNED_PATTERNS.search(product_name):
                # Écarte tôt les catégories interdites par la politique boutique.
                continue

            variants_payload = await daily.cj_variants(product_id)
            variants = variants_payload.get("data")
            if not isinstance(variants, list):
                raise RuntimeError("CJ variantes : liste inattendue")

            detail_payload = await daily.cj_product_detail(product_id)
            image_candidates = set()
            if isinstance(product.get("bigImage"), str):
                image_candidates.add(product["bigImage"])
            image_candidates.update(
                url for url in daily.parse_cj_images(detail_payload)
                if isinstance(url, str)
            )
            for variant in variants:
                if isinstance(variant, dict) and isinstance(
                    variant.get("variantImage"), str
                ):
                    image_candidates.add(variant["variantImage"])

            # Les GET d'images sont faits une fois par produit. Seules deux
            # URLs distinctes réellement lues et validées sont conservées.
            valid_images = []
            checked_urls = set()
            for url in sorted(image_candidates):
                if not isinstance(url, str) or not url.startswith("https://"):
                    continue
                if url in checked_urls:
                    continue
                checked_urls.add(url)
                try:
                    verdict = await daily.check_image(url)
                except Exception:
                    continue
                if isinstance(verdict, dict) and verdict.get("url") == url:
                    valid_images.append(url)
                if len(valid_images) >= 2:
                    break
            images_checked_at = time.time()

            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vid = variant.get("vid")
                sku = str(variant.get("variantSku") or "").strip()
                purchase_price = variant.get("variantSellPrice")
                if not vid or not sku or purchase_price is None:
                    continue
                vid = str(vid)

                stock_payload = await daily.cj_stock(vid)
                stock = daily.cn_stock_of(stock_payload)
                stock_checked_at = time.time()

                freight_payload = await daily.cj_freight(
                    vid, destination, quantity=quantite
                )
                freight_options = freight_payload.get("data")
                if not isinstance(freight_options, list):
                    raise RuntimeError("CJ fret : options de transport inattendues")

                normalized_quotes = []
                for option_index, option in enumerate(freight_options):
                    if not isinstance(option, dict):
                        continue
                    try:
                        shipping_cost = float(option.get("logisticPrice"))
                        aging = str(option.get("logisticAging") or "")
                        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", aging)
                        if match is None:
                            continue
                        min_days, max_days = int(match.group(1)), int(match.group(2))
                        if shipping_cost < 0 or min_days < 1 or max_days < min_days:
                            continue
                    except (TypeError, ValueError):
                        continue

                    quoted_at = time.time()
                    # CJ peut retourner un totalPostageFee distinct de
                    # logisticPrice. Tant que leur relation n'est pas documentée,
                    # un écart rend le devis ambigu et donc non vérifié.
                    raw_total_postage = option.get("totalPostageFee")
                    total_postage_fee = None
                    if raw_total_postage not in (None, ""):
                        try:
                            total_postage_fee = float(raw_total_postage)
                        except (TypeError, ValueError):
                            total_postage_fee = float("nan")
                    freight_mismatch = (
                        total_postage_fee is not None
                        and (
                            not math.isfinite(total_postage_fee)
                            or abs(total_postage_fee - shipping_cost) > 0.01
                        )
                    )
                    normalized_quotes.append({
                        "reference": (
                            f"CJ-LIVE-{vid}-{destination}-{quantite}-"
                            f"{int(quoted_at * 1000)}-{option_index}"
                        ),
                        "verifie": not freight_mismatch,
                        "destination": destination,
                        "quantite": quantite,
                        "cout": shipping_cost,
                        "cout_logistique_cj": shipping_cost,
                        "cout_total_postage_cj": total_postage_fee,
                        "anomalie_tarif": (
                            "totalPostageFee différent de logisticPrice : "
                            "devis suspendu jusqu'à clarification"
                            if freight_mismatch else None
                        ),
                        "devise": self.DEVISE_CJ,
                        "delai_min_jours": min_days,
                        "delai_max_jours": max_days,
                        # CJ n'a pas fourni de preuve structurée de levée des
                        # restrictions douanières dans les réponses observées.
                        "restrictions_ok": False,
                        "verifie_le": quoted_at,
                        "expire_le": quoted_at + self.VALIDITE_INTERNE_DEVIS_SECONDES,
                        "validite_interne_secondes": self.VALIDITE_INTERNE_DEVIS_SECONDES,
                    })

                # Même si aucune option de fret n'est retournée, conserver la
                # candidature permet au moteur de signaler le devis manquant.
                quote_rows = normalized_quotes or [None]
                for quote in quote_rows:
                    offers.append({
                        "fournisseur": self.nom,
                        "pays_fournisseur": "CN",
                        "pays_entrepot": "CN",
                        "sku": sku,
                        "nom_produit": product_name,
                        "prix_achat": purchase_price,
                        "devise_achat": self.DEVISE_CJ,
                        "stock": stock,
                        "stock_verifie": True,
                        "preuve_stock": f"CJ stock/queryById vid={vid} pays=CN",
                        "stock_verifie_le": stock_checked_at,
                        "images_validees": len(valid_images),
                        "images_verifiees_le": images_checked_at,
                        "preuve_images": (
                            f"GET CJ images validées pid={product_id} vid={vid}"
                            if valid_images else ""
                        ),
                        "images_urls_verifiees": list(valid_images),
                        # L'entité légale est identifiée par les conditions
                        # officielles et l'API CJ est authentifiée par daily.py.
                        "fournisseur_verifie": True,
                        "preuve_fournisseur": self.PREUVE_IDENTITE,
                        "entite_juridique_fournisseur": self.FOURNISSEUR_LEGAL,
                        # Les réponses API examinées ne fournissent pas de
                        # certificats/rapports de conformité produit.
                        "conformite_verifiee": False,
                        "preuve_conformite": "",
                        "devis_livraison": quote,
                    })
        return offers


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

    def rechercher_offres(self, mot_cle, destination, quantite):
        """Interroge les adaptateurs actifs qui implémentent le contrat canonique.

        Les pays d'expédition ne filtrent jamais les destinations. Chaque
        offre renvoyée doit ensuite être qualifiée par le moteur commun.
        """
        from collections.abc import Mapping
        from intl import get_country

        get_country(destination)
        if not isinstance(mot_cle, str) or not mot_cle.strip():
            raise ValueError("mot-clé de recherche obligatoire")
        if not isinstance(quantite, int) or isinstance(quantite, bool) or quantite < 1:
            raise ValueError("quantité invalide")

        offers, errors, ignored = [], [], []
        for name, adapter in sorted(self.connectes().items()):
            # Une classe connectée dans le dépôt ne signifie pas que le secret
            # existe dans chaque environnement (CI, poste local, worker).
            # Ne jamais tenter un appel réseau CJ sans sa clé API.
            if name == "cj":
                import os
                if not os.environ.get("CJ_API_KEY"):
                    ignored.append({
                        "fournisseur": name,
                        "raison": "CJ_API_KEY absent dans cet environnement",
                    })
                    continue
            implementation = getattr(type(adapter), "rechercher_offres", None)
            if implementation is AdaptateurFournisseur.rechercher_offres:
                ignored.append({
                    "fournisseur": name,
                    "raison": "connecteur sans recherche normalisée",
                })
                continue
            try:
                result = adapter.rechercher_offres(
                    mot_cle.strip(), destination.upper(), quantite
                )
                if not isinstance(result, (list, tuple)):
                    raise ValueError("le connecteur doit retourner une liste d'offres")
                for offer in result:
                    if not isinstance(offer, Mapping):
                        raise ValueError("offre fournisseur non structurée")
                    normalized = dict(offer)
                    # Le fournisseur vient de l'adaptateur authentifié,
                    # jamais d'une valeur arbitraire fournie dans le flux.
                    normalized["fournisseur"] = name
                    offers.append(normalized)
            except Exception as exc:
                errors.append({
                    "fournisseur": name,
                    "erreur": type(exc).__name__,
                    "detail": str(exc)[:180],
                })
        return {
            "destination": destination.upper(),
            "quantite": quantite,
            "offres": offers,
            "erreurs": errors,
            "adaptateurs_sans_recherche": ignored,
        }

    async def rechercher_offres_async(self, mot_cle, destination, quantite):
        """Recherche asynchrone compatible avec les activités/workflows."""
        from collections.abc import Mapping
        from intl import get_country

        get_country(destination)
        if not isinstance(mot_cle, str) or not mot_cle.strip():
            raise ValueError("mot-clé de recherche obligatoire")
        if not isinstance(quantite, int) or isinstance(quantite, bool) or quantite < 1:
            raise ValueError("quantité invalide")

        offers, errors, ignored = [], [], []
        for name, adapter in sorted(self.connectes().items()):
            if name == "cj":
                import os
                if not os.environ.get("CJ_API_KEY"):
                    ignored.append({
                        "fournisseur": name,
                        "raison": "CJ_API_KEY absent dans cet environnement",
                    })
                    continue
            async_implementation = getattr(type(adapter), "rechercher_offres_async", None)
            sync_implementation = getattr(type(adapter), "rechercher_offres", None)
            if async_implementation is None and (
                sync_implementation is AdaptateurFournisseur.rechercher_offres
            ):
                ignored.append({
                    "fournisseur": name,
                    "raison": "connecteur sans recherche normalisée",
                })
                continue
            try:
                if async_implementation is not None:
                    result = await adapter.rechercher_offres_async(
                        mot_cle.strip(), destination.upper(), quantite
                    )
                else:
                    result = adapter.rechercher_offres(
                        mot_cle.strip(), destination.upper(), quantite
                    )
                if not isinstance(result, (list, tuple)):
                    raise ValueError("le connecteur doit retourner une liste d'offres")
                for offer in result:
                    if not isinstance(offer, Mapping):
                        raise ValueError("offre fournisseur non structurée")
                    normalized = dict(offer)
                    normalized["fournisseur"] = name
                    offers.append(normalized)
            except Exception as exc:
                errors.append({
                    "fournisseur": name,
                    "erreur": type(exc).__name__,
                    "detail": str(exc)[:180],
                })
        return {
            "destination": destination.upper(),
            "quantite": quantite,
            "offres": offers,
            "erreurs": errors,
            "adaptateurs_sans_recherche": ignored,
        }

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
