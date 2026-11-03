"""Tests unitaires du validateur HTTP GET d'images SHOPLINOUS.

Ces tests verifient les controles de securite statiques et les signatures
binaires, sans reseau (les echanges HTTP reels sont couverts par l'execution
du workflow deploye).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.workflows.image_validator import (  # noqa: E402
    _signature_binaire_valide,
    _url_autorisee,
)


def test_schema_https_obligatoire():
    ok, motif = _url_autorisee("http://cf.cjdropshipping.com/img.jpg")
    assert not ok and "HTTPS" in motif


def test_domaine_non_autorise():
    ok, motif = _url_autorisee("https://evil.example.com/img.jpg")
    assert not ok and "non autorise" in motif


def test_hote_interne_refuse():
    ok, motif = _url_autorisee("https://localhost/img.jpg")
    assert not ok and "interne" in motif


def test_identifiants_refuses():
    ok, _ = _url_autorisee("https://user:pass@cf.cjdropshipping.com/img.jpg")
    assert not ok


def test_url_cj_acceptee():
    ok, motif = _url_autorisee("https://cf.cjdropshipping.com/quick/product/a.jpg")
    assert ok, motif


def test_signatures_binaires():
    assert _signature_binaire_valide(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert _signature_binaire_valide(b"\x89PNG\r\n\x1a\n") == "image/png"
    donnees_webp = b"RIFF\x00\x00\x00\x00WEBPVP8 "
    assert _signature_binaire_valide(donnees_webp) == "image/webp"
    assert _signature_binaire_valide(b"<html>pas une image</html>") is None
