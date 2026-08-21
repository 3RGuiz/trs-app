"""Sauvegarde VACUUM INTO — invariant 28 et cas vérifiés du CDC §13.7."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from core import sauvegarde
from core.erreurs import SauvegardeEchouee
from tests.conftest import inserer_production


def _chemin_db(conn):
    return conn.execute("PRAGMA database_list").fetchone()[2]


# Invariant 28 — le fichier produit s'ouvre en SQLite et contient le même nombre
# de lignes de production que la source.
def test_sauvegarde_coherente(base, tmp_path):
    inserer_production(base, "2026-07-13", of_numero="OF-1")
    inserer_production(base, "2026-07-14", of_numero="OF-2")
    destination = tmp_path / "copies"
    cible = sauvegarde.sauvegarder(_chemin_db(base), destination)

    assert cible.exists() and cible.stat().st_size > 0
    copie = sqlite3.connect(str(cible))
    try:
        assert copie.execute("SELECT COUNT(*) FROM production").fetchone()[0] == 2
        assert copie.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        copie.close()
    assert sauvegarde.derniere_reussite(destination / sauvegarde.NOM_JOURNAL) is not None


# Deuxième sauvegarde le même jour : suffixée, jamais d'erreur « file exists ».
def test_deux_sauvegardes_le_meme_jour(base, tmp_path):
    destination = tmp_path / "copies"
    premiere = sauvegarde.sauvegarder(_chemin_db(base), destination)
    seconde = sauvegarde.sauvegarder(_chemin_db(base), destination)
    assert premiere != seconde
    assert seconde.name.endswith("_2.db")


def test_echec_journalise(base, tmp_path):
    # Destination impossible à créer (un fichier occupe le nom du dossier).
    obstacle = tmp_path / "obstacle"
    obstacle.write_text("pas un dossier")
    with pytest.raises((SauvegardeEchouee, OSError)):
        sauvegarde.sauvegarder(_chemin_db(base), obstacle)


# La rotation supprime au-delà de la rétention sans toucher aux copies mensuelles.
def test_rotation(tmp_path):
    destination = tmp_path / "copies"
    destination.mkdir()
    # 40 sauvegardes quotidiennes de juillet et août 2026, dont deux « 1er du mois ».
    jours = [date(2026, 7, j) for j in range(1, 32)] + [date(2026, 8, j) for j in range(1, 10)]
    for jour in jours:
        (destination / f"trs_{jour:%Y-%m-%d}.db").write_bytes(b"x")

    supprimes = sauvegarde.rotation(destination, retention_jours=30, retention_mois=12)

    restants = sorted(f.name for f in destination.glob("trs_*.db"))
    # Les 30 jours les plus récents sont conservés...
    assert "trs_2026-08-09.db" in restants
    assert "trs_2026-07-11.db" in restants          # 30e jour le plus récent
    # ... les plus anciens sont purgés, sauf les copies mensuelles du 1er.
    assert "trs_2026-07-02.db" not in restants
    assert "trs_2026-07-01.db" in restants
    assert "trs_2026-08-01.db" in restants
    assert len(supprimes) == len(jours) - len(restants)
