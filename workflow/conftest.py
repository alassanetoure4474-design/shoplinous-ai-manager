"""Conftest SHOPLINOUS (dossier workflow/).

Garantit que les modules du dossier (daily, ai_manager,
freight_collector_v56, pricing_v55...) sont importables par les tests,
quel que soit le mode d'import de pytest : le run CI #27 a echoue a la
collecte avec ModuleNotFoundError: No module named 'ai_manager'.
L'insertion explicite de ce dossier dans sys.path supprime toute
dependance a l'ordre de collecte."""
import os
import sys

_DOSSIER = os.path.dirname(os.path.abspath(__file__))
if _DOSSIER not in sys.path:
    sys.path.insert(0, _DOSSIER)
