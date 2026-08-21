"""Fixtures communes : base jetable et jeu de données synthétique minimal.

Les noms sont volontairement fictifs (ART-001, Famille A, Zone 1 / Machine 1) :
le dépôt ne porte aucune donnée métier réelle (CLAUDE.md, règle 9).
"""

from __future__ import annotations

from datetime import date

import pytest

from core import arrets, cadences, db, elements, historisation

AUTEUR = "tests"

# Journée de référence du CDC §5.2 bis : cadence 30 ppm, To 840, Tr 570.
JOUR_JUILLET = date(2026, 7, 15)   # mercredi, cadence 30 ppm
JOUR_JUIN = date(2026, 6, 15)      # lundi, cadence 24 ppm


@pytest.fixture
def conn(tmp_path):
    connexion = db.ouvrir_base(tmp_path / "test.db")
    yield connexion
    connexion.close()


@pytest.fixture
def base(conn):
    """Base peuplée : une ligne, trois articles, cadences 24 puis 30 ppm,
    calendrier 5 j/7 à 840/570, historique exploitable depuis le 01/06/2026."""
    conn.execute(
        "INSERT INTO ligne (id, code, libelle, date_debut) VALUES (1, 'LIGNE-1', 'Ligne 1', '2026-01-01')"
    )
    conn.execute("INSERT INTO famille (id, code, libelle) VALUES (1, 'FAM-A', 'Famille A')")
    conn.execute("INSERT INTO famille (id, code, libelle) VALUES (2, 'FAM-B', 'Famille B')")
    for code in ("ART-001", "ART-002", "ART-003"):
        conn.execute(
            "INSERT INTO article (code, libelle) VALUES (?, ?)", (code, f"Article {code}")
        )
        historisation.cloturer_et_inserer(
            conn, "article_famille", {"article_code": code}, {"famille_id": 1},
            "2026-01-01", "Rattachement initial", AUTEUR,
        )
        cadences.changer_cadence(conn, code, 1, 24, "2026-06-01", "Cadence initiale", AUTEUR)
        cadences.changer_cadence(
            conn, code, 1, 30, "2026-07-01", "Capacité relevée au 1er juillet", AUTEUR
        )
    # Calendrier type : 840/570 du lundi au vendredi, fermé le week-end.
    for jour_semaine in range(5):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 840, "tr_min": 570}, "2026-01-01", "Calendrier initial", AUTEUR,
        )
    for jour_semaine in (5, 6):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 0, "tr_min": 0}, "2026-01-01", "Fermeture le week-end", AUTEUR,
        )
    historisation.cloturer_et_inserer(
        conn, "parametre_date", {"cle": "DATE_DEBUT_HISTORIQUE"}, {"valeur": "2026-06-01"},
        "1900-01-01", "Début d'historique exploitable", AUTEUR,
    )
    conn.commit()
    return conn


@pytest.fixture
def arbre(base):
    """Arborescence synthétique : Zone 1 (Machine 1, Machine 2), Zone 2 (Machine 3)."""
    zone1 = elements.ajouter_element(base, 1, None, "ZONE-1", "Zone 1", "ZONE", "2026-01-01")
    zone2 = elements.ajouter_element(base, 1, None, "ZONE-2", "Zone 2", "ZONE", "2026-01-01")
    machine1 = elements.ajouter_element(base, 1, zone1, "MACH-1", "Machine 1", "EQUIPEMENT", "2026-01-01")
    machine2 = elements.ajouter_element(base, 1, zone1, "MACH-2", "Machine 2", "EQUIPEMENT", "2026-01-01")
    machine3 = elements.ajouter_element(base, 1, zone2, "MACH-3", "Machine 3", "EQUIPEMENT", "2026-01-01")
    return {"zone1": zone1, "zone2": zone2,
            "machine1": machine1, "machine2": machine2, "machine3": machine3}


def motif_id(conn, code: str) -> int:
    return conn.execute("SELECT id FROM motif_arret WHERE code = ?", (code,)).fetchone()[0]


def inserer_production(conn, jour, article="ART-001", produite=13_200.0,
                       planifiee=15_000.0, ensachee=None, of_numero="OF-1"):
    conn.execute(
        "INSERT INTO production (date, ligne_id, article_code, of_numero,"
        " qte_planifiee, qte_produite, qte_ensachee) VALUES (?, 1, ?, ?, ?, ?, ?)",
        (jour.isoformat() if isinstance(jour, date) else jour,
         article, of_numero, planifiee, produite, ensachee),
    )
    conn.commit()


def inserer_arret(conn, jour, code_motif="PANNE", debut=None, fin=None,
                  duree=None, element_id=None, arrete_ligne=1):
    return arrets.saisir_arret(
        conn, 1, jour, motif_id(conn, code_motif),
        duree_min=duree, debut=debut, fin=fin,
        element_id=element_id, arrete_ligne=arrete_ligne,
    )
