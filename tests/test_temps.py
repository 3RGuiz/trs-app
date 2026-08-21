"""Cascade des temps — invariants 10, 11, 15, 26, 35 et résolution du calendrier."""

from __future__ import annotations

from datetime import date

import pytest

from core import historisation, indicateurs, temps
from tests.conftest import AUTEUR, JOUR_JUILLET, inserer_arret, inserer_production


def test_resolution_calendrier(base):
    # Jour ouvré : calendrier type.
    assert temps.calendrier_du_jour(base, 1, JOUR_JUILLET) == (840, 570)
    # Week-end : fermé.
    assert temps.calendrier_du_jour(base, 1, "2026-07-18") == (0, 0)
    # L'exception prime sur le calendrier type.
    base.execute(
        "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min, motif)"
        " VALUES (1, '2026-07-15', 0, 0, 'Férié fictif')"
    )
    base.commit()
    assert temps.calendrier_du_jour(base, 1, JOUR_JUILLET) == (0, 0)


# Invariant 10 — absence de conversion horaire : 1 ppm, 300 UVC -> Tu = 300 min.
# Test volontairement trivial : il attrape le facteur 60 parasite.
def test_aucun_facteur_60(base):
    base.execute("DELETE FROM cadence")
    base.commit()
    from core import cadences
    cadences.changer_cadence(base, "ART-001", 1, 1, "2026-06-01", "Cadence 1 ppm", AUTEUR)
    inserer_production(base, JOUR_JUILLET, produite=300)
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    assert df.iloc[0]["Tu"] == 300.0
    assert df.iloc[0]["Tn"] == 300.0


# Invariant 11 — en MODE_TR = 'FIXE', ajouter des arrêts HORS_REQUIS ne modifie
# ni Tr, ni TC, ni aucun indicateur. Garde-fou contre le double comptage.
def test_mode_tr_fixe_ignore_les_arrets_hors_requis(base):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    avant = indicateurs.indicateurs_periode(df)

    inserer_arret(base, JOUR_JUILLET, "NETTOYAGE",
                  debut="2026-07-15 14:00", fin="2026-07-15 16:00")
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    apres = indicateurs.indicateurs_periode(df)

    for cle in ("Tr", "TC", "TRS", "TRG", "TRE", "DO", "TP", "Tf"):
        assert apres[cle] == avant[cle]
    # L'arrêt hors requis reste visible pour information (Pareto), non retranché.
    assert df.iloc[0]["arrets_hors_requis_min"] == 120


def test_mode_tr_calcule(base):
    # En mode CALCULE, Tr = To - arrêts hors requis déclarés.
    historisation.cloturer_et_inserer(
        base, "parametre_date", {"cle": "MODE_TR"}, {"valeur": "CALCULE"},
        "2026-07-01", "Saisie des arrêts fiabilisée", AUTEUR,
    )
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "NETTOYAGE",
                  debut="2026-07-15 14:00", fin="2026-07-15 16:00")
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    assert df.iloc[0]["Tr"] == 840 - 120
    # La bascule est datée : juin reste en mode FIXE.
    assert temps.mode_tr(base, "2026-06-15") == "FIXE"


# Invariant 15 — une période antérieure à la mise en service de la ligne est
# exclue des agrégations, pas comptée comme un TRS de 0 %.
def test_ligne_hors_service_exclue(base):
    df = temps.cascade_journaliere(base, 1, "2025-12-29", "2025-12-31")
    assert set(df["etat"]) == {temps.ETAT_HORS_SERVICE}
    resultat = indicateurs.indicateurs_periode(df)
    assert resultat["TRS"] is None
    assert resultat["Tt"] == 0


# Invariant 35 — les productions antérieures au début d'historique exploitable
# sont stockées mais absentes de toutes les agrégations.
def test_historique_exploitable(base):
    inserer_production(base, "2026-04-15", produite=10_000)   # antérieur au 01/06
    df = temps.cascade_journaliere(base, 1, "2026-04-15", "2026-04-15")
    assert df.iloc[0]["etat"] == temps.ETAT_HORS_HISTORIQUE
    assert df.iloc[0]["Tu"] == 0
    # La donnée reste en base.
    assert base.execute(
        "SELECT COUNT(*) FROM production WHERE date = '2026-04-15'"
    ).fetchone()[0] == 1


# Invariant 26 — données manquantes ≠ production nulle : un jour requis sans
# ligne importée est un état distinct, exclu des moyennes, jamais un TRS de 0 %.
def test_donnees_manquantes_distinctes_de_production_nulle(base):
    inserer_production(base, "2026-07-13", produite=13_200)
    # 2026-07-14 : jour requis, aucune ligne importée.
    inserer_production(base, "2026-07-15", produite=13_200)
    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-15")
    assert list(df["etat"]) == [temps.ETAT_OK, temps.ETAT_DONNEES_MANQUANTES, temps.ETAT_OK]
    assert temps.jours_donnees_manquantes(df) == [date(2026, 7, 14)]

    resultat = indicateurs.indicateurs_periode(df)
    # Le jour manquant n'entre pas dans les sommes : Tr = 2 jours, pas 3.
    assert resultat["Tr"] == 2 * 570
    assert resultat["TRS"] == pytest.approx((2 * 13_200 / 30) / (2 * 570))
    assert resultat["nb_jours_donnees_manquantes"] == 1

    # Une production réellement nulle, déclarée, donne bien un TRS de 0 %.
    inserer_production(base, "2026-07-16", produite=0)
    df = temps.cascade_journaliere(base, 1, "2026-07-16", "2026-07-16")
    assert df.iloc[0]["etat"] == temps.ETAT_OK
    assert indicateurs.indicateurs_periode(df)["TRS"] == 0.0


def test_hierarchie_des_temps(base):
    # Invariant 3 — Tu <= Tn <= Tf <= Tr <= To <= Tt sur un jeu cohérent.
    inserer_production(base, JOUR_JUILLET, produite=13_200, ensachee=13_500)
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    jour = df.iloc[0]
    assert jour["Tu"] <= jour["Tn"] <= jour["Tf"] <= jour["Tr"] <= jour["To"] <= jour["Tt"]
