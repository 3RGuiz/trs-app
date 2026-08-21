"""Résolution des cadences par date — invariant 36 et garde-fous du CDC §4.2."""

from __future__ import annotations

import pytest

from core import cadences, indicateurs, temps
from core.erreurs import ErreurMetier
from tests.conftest import AUTEUR, JOUR_JUILLET, JOUR_JUIN, inserer_production


def test_cadence_applicable(base):
    assert cadences.cadence_applicable(base, "ART-001", 1, JOUR_JUIN)["valeur_ppm"] == 24
    assert cadences.cadence_applicable(base, "ART-001", 1, JOUR_JUILLET)["valeur_ppm"] == 30
    assert cadences.cadence_applicable(base, "ART-001", 1, "2026-05-01") is None


# Invariant 36 — juin à 24 ppm, juillet à 30 ppm, et modifier la cadence de
# juillet ne change pas le résultat de juin. C'est le premier cas réel de
# changement de cadence : s'il fonctionne, l'historisation fonctionne.
def test_bascule_de_cadence_au_premier_juillet(base):
    inserer_production(base, JOUR_JUIN, produite=13_200)
    inserer_production(base, JOUR_JUILLET, produite=13_200)

    df_juin = temps.cascade_journaliere(base, 1, JOUR_JUIN, JOUR_JUIN)
    df_juillet = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    trs_juin = indicateurs.indicateurs_periode(df_juin)["TRS"]
    trs_juillet = indicateurs.indicateurs_periode(df_juillet)["TRS"]

    # Même production : 13 200 / (24 x 570) en juin, 13 200 / (30 x 570) en juillet.
    assert trs_juin == pytest.approx(13_200 / (24 * 570))
    assert trs_juillet == pytest.approx(13_200 / (30 * 570))

    # La barre a monté : le TRS affiché baisse sans dégradation réelle (CDC §4.2).
    assert trs_juin > trs_juillet

    # Modifier la cadence de juillet ne touche pas juin.
    cadences.changer_cadence(base, "ART-001", 1, 45, "2026-08-01",
                             "Débridage du conditionnement", AUTEUR)
    df_juin_apres = temps.cascade_journaliere(base, 1, JOUR_JUIN, JOUR_JUIN)
    assert indicateurs.indicateurs_periode(df_juin_apres)["TRS"] == trs_juin


def test_production_sans_cadence_exclue_et_signalee(base):
    # Une production avant toute cadence : jamais calculée avec une valeur par défaut.
    base.execute(
        "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min)"
        " VALUES (1, '2026-05-04', 840, 570)"
    )
    # 2026-05-04 est un lundi : le calendrier type s'applique déjà, l'exception est
    # identique — elle fixe simplement le décor. La cadence, elle, n'existe pas encore.
    base.commit()
    inserer_production(base, "2026-07-13", produite=6_000)          # cadence connue
    base.execute(
        "INSERT INTO production (date, ligne_id, article_code, of_numero, qte_produite)"
        " VALUES ('2026-07-13', 1, 'ART-002', 'OF-9', 5000)"
    )
    base.execute("DELETE FROM cadence WHERE article_code = 'ART-002'")
    base.commit()

    df = temps.cascade_journaliere(base, 1, "2026-07-13", "2026-07-13")
    resultat = indicateurs.indicateurs_periode(df)
    assert resultat["lignes_sans_cadence"] == 1
    assert resultat["Tu"] == pytest.approx(6_000 / 30)   # la ligne sans cadence est exclue
    assert any("sans cadence" in alerte for alerte in resultat["alertes"])


def test_cadence_invalide_refusee(base):
    for valeur in (0, -5, None):
        with pytest.raises(ErreurMetier):
            cadences.changer_cadence(base, "ART-001", 1, valeur, "2026-10-01",
                                     "Valeur invalide", AUTEUR)


def test_dates_changement_pour_reperes_visuels(base):
    # La première cadence n'est pas un changement ; le 01/07 en est un.
    assert cadences.dates_changement(base, 1) == ["2026-07-01"]
    assert cadences.dates_changement(base, 1, "2026-07-05", "2026-08-31") == []
