"""Socle d'historisation : non-chevauchement, journal, non-régression du passé.

Couvre les invariants 6 (non-régression générique, paramétré par table),
13 (non-chevauchement) et 14 (journal obligatoire) du CDC §5.5.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core import historisation, indicateurs, motifs, temps
from core.erreurs import ChevauchementPeriode, CommentaireObligatoire, ErreurMetier
from tests.conftest import AUTEUR, JOUR_JUIN, JOUR_JUILLET, inserer_arret, inserer_production, motif_id


def test_cloture_et_insertion_ferment_l_ancienne_periode(base):
    lignes = historisation.historique(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1}
    )
    assert len(lignes) == 2
    assert lignes[0]["valeur_ppm"] == 24
    assert lignes[0]["date_fin"] == "2026-06-30"   # clôturée la veille de la prise d'effet
    assert lignes[1]["valeur_ppm"] == 30
    assert lignes[1]["date_fin"] is None


def test_resolution_a_la_date(base):
    assert historisation.resoudre(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1}, JOUR_JUIN
    )["valeur_ppm"] == 24
    assert historisation.resoudre(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1}, JOUR_JUILLET
    )["valeur_ppm"] == 30
    assert historisation.resoudre(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1}, "2026-05-01"
    ) is None


# Invariant 13 — insérer une période qui en recouvre une autre lève une erreur
# explicite, jamais un enregistrement silencieux.
def test_non_chevauchement(base):
    with pytest.raises(ChevauchementPeriode):
        historisation.valider_non_chevauchement(
            base, "cadence", {"article_code": "ART-001", "ligne_id": 1},
            "2026-06-15", "2026-07-15",
        )
    # Une période entièrement libre passe.
    historisation.valider_non_chevauchement(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1},
        "2026-01-01", "2026-05-31",
    )


def test_prise_d_effet_le_meme_jour_refusee(base):
    with pytest.raises(ChevauchementPeriode):
        historisation.cloturer_et_inserer(
            base, "cadence", {"article_code": "ART-001", "ligne_id": 1},
            {"valeur_ppm": 32}, "2026-07-01", "Doublon de date d'effet", AUTEUR,
        )


# Invariant 14 — toute écriture crée exactement une entrée de journal,
# et un commentaire vide est refusé.
def test_journal_obligatoire(base):
    avant = base.execute("SELECT COUNT(*) FROM journal_referentiel").fetchone()[0]
    historisation.cloturer_et_inserer(
        base, "cadence", {"article_code": "ART-001", "ligne_id": 1},
        {"valeur_ppm": 45}, "2026-09-01", "Débridage du conditionnement", AUTEUR,
    )
    apres = base.execute("SELECT COUNT(*) FROM journal_referentiel").fetchone()[0]
    assert apres == avant + 1

    for commentaire in ("", "   ", None):
        with pytest.raises(CommentaireObligatoire):
            historisation.cloturer_et_inserer(
                base, "cadence", {"article_code": "ART-002", "ligne_id": 1},
                {"valeur_ppm": 45}, "2026-09-01", commentaire, AUTEUR,
            )


def test_table_non_declaree_refusee(base):
    with pytest.raises(ErreurMetier):
        historisation.resoudre(base, "production", {"id": 1}, JOUR_JUILLET)


def test_resoudre_en_masse_équivaut_à_resoudre(base):
    df = pd.DataFrame({
        "article_code": ["ART-001", "ART-001", "ART-002", "ART-001"],
        "ligne_id": [1, 1, 1, 1],
        "date": ["2026-06-10", "2026-07-10", "2026-07-20", "2026-05-01"],
    })
    referentiel = pd.read_sql_query(
        "SELECT article_code, ligne_id, valeur_ppm, date_debut, date_fin FROM cadence", base
    )
    resolu = historisation.resoudre_en_masse(referentiel, df, ["article_code", "ligne_id"], "date")
    assert list(resolu["valeur_ppm"][:3]) == [24, 30, 30]
    assert pd.isna(resolu["valeur_ppm"].iloc[3])   # avant toute cadence : jamais de défaut


# ---------------------------------------------------------------------------
# Invariant 6 — le test de non-régression le plus important du projet :
# après modification de CHAQUE table de référentiel avec une date d'effet
# postérieure, recalculer une période antérieure donne strictement le même
# résultat qu'avant.
# ---------------------------------------------------------------------------

def _indicateurs_juillet(conn):
    df = temps.cascade_journaliere(conn, 1, "2026-07-13", "2026-07-17")
    resultat = indicateurs.indicateurs_periode(df)
    return {cle: resultat[cle] for cle in ("TRS", "TRG", "TRE", "TC", "TS", "Tu", "Tr", "To", "Tt")}


MODIFICATIONS = {
    "cadence": lambda conn: historisation.cloturer_et_inserer(
        conn, "cadence", {"article_code": "ART-001", "ligne_id": 1},
        {"valeur_ppm": 45}, "2026-09-01", "Changement postérieur", AUTEUR),
    "calendrier_type": lambda conn: historisation.cloturer_et_inserer(
        conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": 2},
        {"to_min": 960, "tr_min": 700}, "2026-09-01", "Changement postérieur", AUTEUR),
    "motif_classement": lambda conn: historisation.cloturer_et_inserer(
        conn, "motif_classement", {"motif_id": motif_id(conn, "PANNE")},
        {"categorie": "HORS_REQUIS", "famille": None},
        "2026-09-01", "Changement postérieur", AUTEUR),
    "article_famille": lambda conn: historisation.cloturer_et_inserer(
        conn, "article_famille", {"article_code": "ART-001"},
        {"famille_id": 2}, "2026-09-01", "Changement postérieur", AUTEUR),
    "parametre_date": lambda conn: historisation.cloturer_et_inserer(
        conn, "parametre_date", {"cle": "MODE_TR"},
        {"valeur": "CALCULE"}, "2026-09-01", "Changement postérieur", AUTEUR),
}


@pytest.mark.parametrize("table", sorted(MODIFICATIONS))
def test_non_regression_du_passe(base, table):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    avant = _indicateurs_juillet(base)
    MODIFICATIONS[table](base)
    apres = _indicateurs_juillet(base)
    assert apres == avant, f"La modification de {table} a réécrit le passé"


def test_reclassement_motif_ne_touche_pas_le_passe(base):
    # Invariant 22 — reclasser un motif avec date d'effet ne modifie aucun
    # indicateur antérieur à cette date.
    panne = motif_id(base, "PANNE")
    assert motifs.categorie_motif(base, panne, JOUR_JUILLET) == "ARRET_PROPRE"
    motifs.reclasser_motif(base, panne, "HORS_REQUIS", "2026-08-01",
                           "Décision de politique de mesure", AUTEUR)
    assert motifs.categorie_motif(base, panne, JOUR_JUILLET) == "ARRET_PROPRE"
    assert motifs.categorie_motif(base, panne, "2026-08-15") == "HORS_REQUIS"
