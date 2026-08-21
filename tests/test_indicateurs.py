"""Tests d'invariants du moteur d'indicateurs (CDC §5.5) — bloquants.

Couvre : télescopage (1, 2), cas de référence §5.2 bis (8) et sa variante 45 ppm,
équivalence des deux formulations du TRS (9), niveau 1 sans arrêts (24),
bascule de niveau (25), constance de TC et TS (12).
"""

from __future__ import annotations

import random

import pytest

from core import indicateurs, temps
from tests.conftest import JOUR_JUILLET, inserer_arret, inserer_production


def _resultat_jour(conn, jour=JOUR_JUILLET):
    df = temps.cascade_journaliere(conn, 1, jour, jour)
    return indicateurs.indicateurs_periode(df)


# ---------------------------------------------------------------- cas de référence

# CDC §5.2 bis : cadence 30 ppm, To 840, Tr 570, 13 200 UVC produites,
# Tf 500 min (70 min d'arrêts propres), compteur ensacheuse 13 500.
def _installer_cas_de_reference(conn, ensachee=13_500.0):
    inserer_production(conn, JOUR_JUILLET, produite=13_200, planifiee=15_000,
                       ensachee=ensachee)
    inserer_arret(conn, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")   # 70 min


# Invariant 8 — les huit résultats à 0,01 point près.
def test_cas_de_reference(base):
    _installer_cas_de_reference(base)
    resultat = _resultat_jour(base)
    assert resultat["TRS"] == pytest.approx(0.7719, abs=1e-4)
    assert resultat["TRG"] == pytest.approx(0.5238, abs=1e-4)
    assert resultat["TRE"] == pytest.approx(0.3056, abs=1e-4)
    assert resultat["TC"] == pytest.approx(0.6786, abs=1e-4)
    assert resultat["TS"] == pytest.approx(0.5833, abs=1e-4)
    assert resultat["TQ"] == pytest.approx(0.9778, abs=1e-4)
    assert resultat["TP"] == pytest.approx(0.9000, abs=1e-4)
    assert resultat["DO"] == pytest.approx(0.8772, abs=1e-4)
    assert resultat["Tu"] == pytest.approx(440.0)
    assert resultat["Tn"] == pytest.approx(450.0)
    assert resultat["Tf"] == pytest.approx(500.0)


# Variante à 45 ppm — verrouille l'exigence de comparabilité du §4.2 :
# l'écart vient du changement de référence, d'aucune dégradation réelle.
def test_variante_45_ppm(base):
    from core import cadences
    base.execute("DELETE FROM cadence")
    base.commit()
    cadences.changer_cadence(base, "ART-001", 1, 45, "2026-06-01",
                             "Référence après débridage", "tests")
    _installer_cas_de_reference(base)
    resultat = _resultat_jour(base)
    assert resultat["TP"] == pytest.approx(0.6000, abs=1e-4)
    assert resultat["TRS"] == pytest.approx(0.5146, abs=1e-4)


# Invariants 1 et 2 — télescopage : TQ x TP x DO == Tu / Tr (à 1e-9 près),
# TRG == Tu / To et TRE == Tu / Tt.
def test_telescopage(base):
    _installer_cas_de_reference(base)
    resultat = _resultat_jour(base)
    assert resultat["TQ"] * resultat["TP"] * resultat["DO"] == pytest.approx(
        resultat["Tu"] / resultat["Tr"], abs=1e-9
    )
    assert resultat["TRS"] == pytest.approx(resultat["Tu"] / resultat["Tr"], abs=1e-9)
    assert resultat["TRG"] == pytest.approx(resultat["Tu"] / resultat["To"], abs=1e-9)
    assert resultat["TRE"] == pytest.approx(resultat["Tu"] / resultat["Tt"], abs=1e-9)


# Invariant 9 — équivalence des deux formulations du TRS, sur le cas de
# référence et sur un jeu aléatoire de 1 000 journées.
def test_equivalence_des_deux_formulations(base):
    _installer_cas_de_reference(base)
    resultat = _resultat_jour(base)
    assert resultat["TRS"] == pytest.approx(13_200 / (30 * 570), abs=1e-9)

    generateur = random.Random(2026)
    for _ in range(1_000):
        cadence = generateur.uniform(1, 60)
        tr = generateur.uniform(60, 1_440)
        quantite = generateur.uniform(0, cadence * tr * 1.2)
        tu = quantite / cadence
        assert quantite / (cadence * tr) == pytest.approx(tu / tr, rel=1e-12)


# Invariant 24 — niveau 1 : sans arrêt saisi et sans compteur, TRS/TRG/TRE sont
# exacts ; TQ, TP, DO valent None (« non mesuré »), jamais 1,0.
def test_niveau_1_sans_arrets(base):
    inserer_production(base, JOUR_JUILLET, produite=13_200)
    resultat = _resultat_jour(base)
    assert resultat["TRS"] == pytest.approx(0.7719, abs=1e-4)
    assert resultat["TRG"] == pytest.approx(0.5238, abs=1e-4)
    assert resultat["TRE"] == pytest.approx(0.3056, abs=1e-4)
    assert resultat["TQ"] is None
    assert resultat["TP"] is None
    assert resultat["DO"] is None
    assert resultat["niveau_donnees"] == 1
    assert any("non mesuré" in alerte for alerte in resultat["alertes"])


# Invariant 25 — ajouter les arrêts puis le compteur ne modifie ni TRS, ni TRG,
# ni TRE : seule la décomposition apparaît.
def test_bascule_de_niveau(base):
    inserer_production(base, JOUR_JUILLET, produite=13_200)
    niveau_1 = _resultat_jour(base)

    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    niveau_2 = _resultat_jour(base)
    assert niveau_2["niveau_donnees"] == 2
    assert niveau_2["DO"] is not None and niveau_2["TP"] is not None
    assert niveau_2["TQ"] is None

    base.execute("UPDATE production SET qte_ensachee = 13500 WHERE date = '2026-07-15'")
    base.commit()
    niveau_3 = _resultat_jour(base)
    assert niveau_3["niveau_donnees"] == 3
    assert niveau_3["TQ"] is not None

    for cle in ("TRS", "TRG", "TRE"):
        assert niveau_1[cle] == pytest.approx(niveau_2[cle], abs=1e-12)
        assert niveau_2[cle] == pytest.approx(niveau_3[cle], abs=1e-12)


# Invariant 12 — constance de TC et TS avec le calendrier par défaut, quelle que
# soit la période agrégée sur des jours de production complets.
def test_constance_tc_ts(base):
    for jour in ("2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"):
        inserer_production(base, jour, produite=10_000, of_numero=f"OF-{jour}")
    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-17")
    resultat = indicateurs.indicateurs_periode(df)
    assert resultat["TC"] == pytest.approx(570 / 840, abs=1e-9)
    assert resultat["TS"] == pytest.approx(840 / 1440, abs=1e-9)


def test_denominateur_nul_donne_none(base):
    # Jour fermé : Tr = 0 -> indicateurs None, jamais de division par zéro.
    df = temps.cascade_journaliere(base, 1, "2026-07-18", "2026-07-18")   # samedi
    resultat = indicateurs.indicateurs_periode(df)
    assert resultat["TRS"] is None
    assert resultat["TC"] is None


def test_depassement_de_capacite_signale_sans_plafonnement(base):
    inserer_production(base, JOUR_JUILLET, produite=18_000)   # > 17 100 produisibles
    resultat = _resultat_jour(base)
    assert resultat["TRS"] > 1                                # jamais plafonné
    assert any("sous-évaluée" in alerte for alerte in resultat["alertes"])
