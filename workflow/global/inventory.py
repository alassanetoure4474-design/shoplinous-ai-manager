"""Inventory Manager : stocks agreges par variante et alertes.

N agregate QUE des mesures fournies (API reelle ou import declare) ;
aucun stock n est devine. Le seuil d alerte est configurable.
"""

class GestionnaireStocks:
    def __init__(self, seuil_alerte=10):
        self.seuil_alerte = seuil_alerte
        self._stocks = {}  # (fournisseur, vid) -> {"stock": int, ...}

    def enregistrer_mesure(self, fournisseur, vid, stock, source="api"):
        if not isinstance(stock, int) or stock < 0:
            raise ValueError("stock invalide: " + repr(stock))
        self._stocks[(fournisseur, vid)] = {
            "stock": stock, "source": source}

    def stock(self, fournisseur, vid):
        mesure = self._stocks.get((fournisseur, vid))
        if mesure is None:
            return None  # jamais de stock invente
        return mesure["stock"]

    def disponible(self, fournisseur, vid, quantite):
        stock = self.stock(fournisseur, vid)
        if stock is None:
            return False  # non mesure = non garanti
        return stock >= quantite

    def alertes(self):
        return [{"fournisseur": f, "vid": v, "stock": m["stock"]}
                for (f, v), m in sorted(self._stocks.items())
                if m["stock"] <= self.seuil_alerte]
