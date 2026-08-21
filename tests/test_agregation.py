"""Agrégation — invariants 4 (anti-« moyenne de taux »), 5 (conservation) et
27 (pas de TRS par article) du CDC §5.5."""

from __future__ import annotations

import pytest

from core import agregation, historisation, indicateurs, temps
from tests.conftest import AUTEUR, inserer_production


def _semaine_contrastee(base):
    """Une semaine où les journées n'ont pas le même poids : la moyenne des TRS
    journaliers y est fausse, seule la somme des temps est juste."""
    # Mercredi devient une petite journée : To 420 / Tr 300.
    base.execute(
        "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min, motif)"
        " VALUES (1, '2026-07-15', 420, 300, 'Journée réduite')"
    )
    base.commit()
    inserer_production(base, "2026-07-13", produite=13_200, of_numero="OF-1")
    inserer_production(base, "2026-07-14", produite=9_000, of_numero="OF-2")
    inserer_production(base, "2026-07-15", produite=2_000, of_numero="OF-3")
    inserer_production(base, "2026-07-16", produite=15_000, of_numero="OF-4")
    inserer_production(base, "2026-07-17", produite=11_500, of_numero="OF-5")


# Invariant 4 — le TRS d'une semaine égale le TRS recalculé sur la somme des
# temps des jours, et diffère de la moyenne des TRS journaliers.
def test_agregation_par_somme_des_temps(base):
    _semaine_contrastee(base)
    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-19")

    par_semaine = agregation.agreger_par_periode(df, "semaine")
    assert len(par_semaine) == 1
    trs_semaine = par_semaine.iloc[0]["TRS"]

    somme = indicateurs.sommer_temps(df)
    assert trs_semaine == pytest.approx(somme["Tu"] / somme["Tr"], abs=1e-12)

    par_jour = agregation.agreger_par_periode(df, "jour")
    trs_journaliers = par_jour["TRS"].dropna()
    moyenne_des_taux = trs_journaliers.mean()
    assert trs_semaine != pytest.approx(moyenne_des_taux, abs=1e-4)


def test_cles_de_periode_iso(base):
    _semaine_contrastee(base)
    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-19")
    assert list(agregation.agreger_par_periode(df, "semaine")["periode"]) == ["2026-S29"]
    assert list(agregation.agreger_par_periode(df, "mois")["periode"]) == ["2026-07"]
    assert list(agregation.agreger_par_periode(df, "annee")["periode"]) == ["2026"]


# Invariant 5 — conservation : la somme des Tu par article égale le Tu global.
def test_conservation_du_temps_par_article(base):
    inserer_production(base, "2026-07-13", article="ART-001", produite=8_000, of_numero="OF-1")
    inserer_production(base, "2026-07-13", article="ART-002", produite=5_200, of_numero="OF-2")
    inserer_production(base, "2026-07-14", article="ART-003", produite=6_000, of_numero="OF-3")

    par_article = agregation.par_article(base, 1, "2026-07-13", "2026-07-14")
    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-14")
    tu_ligne = indicateurs.sommer_temps(df)["Tu"]
    assert par_article["temps_theorique_min"].sum() == pytest.approx(tu_ligne, abs=1e-9)

    par_famille = agregation.par_famille(base, 1, "2026-07-13", "2026-07-14")
    assert par_famille["temps_theorique_min"].sum() == pytest.approx(tu_ligne, abs=1e-9)


# Invariant 27 — aucune fonction d'agrégation par article ne retourne de TRS.
def test_pas_de_trs_par_article(base):
    inserer_production(base, "2026-07-13", article="ART-001", produite=8_000)
    for df in (
        agregation.par_article(base, 1, "2026-07-01", "2026-07-31"),
        agregation.par_famille(base, 1, "2026-07-01", "2026-07-31"),
    ):
        colonnes = {c.upper() for c in df.columns}
        assert not colonnes & {"TRS", "TRG", "TRE"}
        assert "taux_realisation" in df.columns


def test_taux_de_realisation(base):
    inserer_production(base, "2026-07-13", article="ART-001",
                       produite=12_000, planifiee=15_000)
    par_article = agregation.par_article(base, 1, "2026-07-13", "2026-07-13")
    assert par_article.iloc[0]["taux_realisation"] == pytest.approx(0.8)


def test_vue_famille_historique_et_actuelle(base):
    # ART-001 produit en juillet dans Famille A, puis reclassé en Famille B en août.
    inserer_production(base, "2026-07-13", article="ART-001", produite=6_000)
    historisation.cloturer_et_inserer(
        base, "article_famille", {"article_code": "ART-001"}, {"famille_id": 2},
        "2026-08-01", "Réorganisation du catalogue", AUTEUR,
    )
    historique = agregation.par_famille(base, 1, "2026-07-01", "2026-07-31", vue="historique")
    actuelle = agregation.par_famille(base, 1, "2026-07-01", "2026-07-31", vue="actuelle")
    # Vue historique : la production reste comptée dans la famille de l'époque.
    assert dict(zip(historique["famille"], historique["qte_produite"]))["Famille A"] == 6_000
    # Vue catalogue actuel : recomptée avec le rattachement d'aujourd'hui.
    assert dict(zip(actuelle["famille"], actuelle["qte_produite"]))["Famille B"] == 6_000
