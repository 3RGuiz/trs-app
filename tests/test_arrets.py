"""Union des intervalles d'arrêt — invariants 16 et 17, cas limites du CDC §4.6."""

from __future__ import annotations

from datetime import datetime

import pytest

from core import arrets, indicateurs, temps
from tests.conftest import JOUR_JUILLET, inserer_arret, inserer_production


def _iv(debut: str, fin: str):
    return (datetime.fromisoformat(f"2026-07-15 {debut}"),
            datetime.fromisoformat(f"2026-07-15 {fin}"))


# Les cinq cas vérifiés du CDC §4.6, à reprendre tels quels.
CAS_UNION = [
    ("chevauchement partiel", [_iv("08:00", "08:20"), _iv("08:10", "08:35")], 35),
    ("inclusion totale", [_iv("08:00", "08:40"), _iv("08:10", "08:20")], 40),
    ("contiguïté exacte", [_iv("08:00", "08:20"), _iv("08:20", "08:30")], 30),
    ("disjoints", [_iv("08:00", "08:10"), _iv("08:40", "09:00")], 30),
    ("triple recouvrement",
     [_iv("08:00", "08:20"), _iv("08:15", "08:50"), _iv("08:45", "09:00")], 60),
]


@pytest.mark.parametrize("nom,intervalles,attendu", CAS_UNION, ids=[c[0] for c in CAS_UNION])
def test_duree_union(nom, intervalles, attendu):
    assert arrets.duree_union(intervalles) == attendu


def test_duree_union_vide():
    assert arrets.duree_union([]) == 0.0


# Invariant 16 — deux arrêts de sections différentes sur des fenêtres qui se
# recouvrent comptent pour la durée de leur union, pas pour la somme.
def test_union_dans_la_cascade(base, arbre):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"],
                  debut="2026-07-15 08:00", fin="2026-07-15 08:20")
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine3"],
                  debut="2026-07-15 08:10", fin="2026-07-15 08:35")
    du_jour = arrets.temps_arrets_jour(base, 1, JOUR_JUILLET)
    assert du_jour["ARRET_PROPRE"] == 35          # union, pas 45
    assert du_jour["avertissement_horodatage"] is False


# Repli sans horodatage : somme des durées, avec avertissement — jamais silencieux.
def test_repli_sans_horodatage(base):
    inserer_arret(base, JOUR_JUILLET, "PANNE", duree=20)
    inserer_arret(base, JOUR_JUILLET, "PANNE", duree=25)
    du_jour = arrets.temps_arrets_jour(base, 1, JOUR_JUILLET)
    assert du_jour["ARRET_PROPRE"] == 45
    assert du_jour["avertissement_horodatage"] is True


# Invariant 17 — un arrêt absorbé par un tampon (arrete_ligne = 0) apparaît dans
# le Pareto et ne modifie ni Tf, ni Tr, ni aucun indicateur.
def test_arret_absorbe_sans_effet_sur_la_cascade(base, arbre):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"],
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    avant = indicateurs.indicateurs_periode(df)

    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine2"],
                  debut="2026-07-15 10:00", fin="2026-07-15 10:30", arrete_ligne=0)
    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    apres = indicateurs.indicateurs_periode(df)

    for cle in ("TRS", "TRG", "TRE", "DO", "TP", "Tf", "Tr"):
        assert apres[cle] == avant[cle]
    pareto = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="element")
    assert pareto["duree_min"].sum() == 100        # 70 + 30 : le Pareto voit tout


# Union séparée par catégorie, sur les seuls arrêts qui stoppent la ligne.
def test_union_par_categorie(base):
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 08:00", fin="2026-07-15 08:30")
    inserer_arret(base, JOUR_JUILLET, "NETTOYAGE",
                  debut="2026-07-15 08:00", fin="2026-07-15 08:30")
    du_jour = arrets.temps_arrets_jour(base, 1, JOUR_JUILLET)
    assert du_jour["ARRET_PROPRE"] == 30
    assert du_jour["HORS_REQUIS"] == 30


def test_fin_avant_debut_refusee(base):
    from core.erreurs import ErreurMetier
    with pytest.raises(ErreurMetier):
        inserer_arret(base, JOUR_JUILLET, "PANNE",
                      debut="2026-07-15 09:00", fin="2026-07-15 08:00")


# Validations du CDC §4.6 : un cumul d'arrêts ne peut pas dépasser le temps
# disponible du jour — au-delà, c'est une erreur de saisie ou de calendrier.
def test_cumul_d_arrets_superieur_au_temps_requis_refuse(base):
    from core.erreurs import ErreurMetier

    # Tr = 570 min. Un premier arrêt de 500 min passe.
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 06:00", fin="2026-07-15 14:20")
    # Le second porterait le cumul à 620 min : refusé, avec explication.
    with pytest.raises(ErreurMetier, match="temps requis"):
        inserer_arret(base, JOUR_JUILLET, "PANNE",
                      debut="2026-07-15 15:00", fin="2026-07-15 17:00")
    # L'arrêt refusé n'a pas été enregistré.
    assert base.execute(
        "SELECT COUNT(*) FROM arret WHERE date = ?", (JOUR_JUILLET.isoformat(),)
    ).fetchone()[0] == 1


def test_arrets_hors_requis_plafonnes_au_temps_d_ouverture(base):
    from core.erreurs import ErreurMetier

    # To = 840 min pour les arrêts hors requis, pas 570.
    inserer_arret(base, JOUR_JUILLET, "NETTOYAGE",
                  debut="2026-07-15 06:00", fin="2026-07-15 16:00")   # 600 min
    with pytest.raises(ErreurMetier, match="temps d'ouverture"):
        inserer_arret(base, JOUR_JUILLET, "NETTOYAGE",
                      debut="2026-07-15 16:00", fin="2026-07-15 21:00")   # +300


def test_arret_absorbe_echappe_au_plafond(base):
    # Un arrêt à arrete_ligne = 0 n'entre pas dans la cascade : il ne consomme
    # aucun temps et ne doit donc pas être plafonné.
    inserer_arret(base, JOUR_JUILLET, "PANNE",
                  debut="2026-07-15 06:00", fin="2026-07-15 15:00")   # 540 min
    inserer_arret(base, JOUR_JUILLET, "PANNE", arrete_ligne=0,
                  debut="2026-07-15 16:00", fin="2026-07-15 20:00")   # +240 absorbées
    assert arrets.temps_arrets_jour(base, 1, JOUR_JUILLET)["ARRET_PROPRE"] == 540


def test_alerte_element_hors_service(base, arbre):
    # Non bloquant : mieux vaut conserver l'arrêt avec une alerte que perdre
    # l'information (CDC §4.6).
    from core import elements
    elements.retirer_element(base, arbre["machine1"], "2026-07-01")

    alerte = arrets.verifier_element_en_service(base, arbre["machine1"], JOUR_JUILLET)
    assert alerte is not None and "retiré du service" in alerte
    # La saisie reste possible.
    arret_id = inserer_arret(base, JOUR_JUILLET, "PANNE",
                             element_id=arbre["machine1"], duree=20)
    assert arret_id is not None
    # Aucune alerte quand l'élément est bien en service.
    assert arrets.verifier_element_en_service(base, arbre["machine2"], JOUR_JUILLET) is None


def test_duree_negative_refusee(base):
    from core.erreurs import ErreurMetier
    with pytest.raises(ErreurMetier):
        inserer_arret(base, JOUR_JUILLET, "PANNE", duree=-10)


def test_pareto_origine_non_renseignee(base):
    inserer_arret(base, JOUR_JUILLET, "PANNE", duree=15)   # sans élément d'origine
    pareto = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="element")
    assert list(pareto["libelle"]) == ["Origine non renseignée"]
