"""Arborescence de la ligne — invariants 18, 19, 20, 37 du CDC §5.5."""

from __future__ import annotations

import pytest

from core import arrets, elements, indicateurs, temps
from core.erreurs import ErreurMetier, SuppressionInterdite
from tests.conftest import (AUTEUR, JOUR_JUILLET, inserer_arret,
                            inserer_production)


def _indicateurs_du_jour(conn):
    df = temps.cascade_journaliere(conn, 1, JOUR_JUILLET, JOUR_JUILLET)
    resultat = indicateurs.indicateurs_periode(df)
    return {cle: resultat[cle] for cle in ("TRS", "TRG", "TRE", "DO", "TP", "Tf", "Tr", "Tu")}


def test_chemin_materialise(base, arbre):
    zone1 = base.execute(
        "SELECT chemin FROM element_ligne WHERE id = ?", (arbre["zone1"],)
    ).fetchone()[0]
    machine1 = base.execute(
        "SELECT chemin FROM element_ligne WHERE id = ?", (arbre["machine1"],)
    ).fetchone()[0]
    assert zone1 == f"/{arbre['zone1']}/"
    assert machine1 == f"/{arbre['zone1']}/{arbre['machine1']}/"
    assert elements.ancetres(base, arbre["machine1"]) == [arbre["zone1"]]


# Invariant 18 — neutralité de l'élément : déplacer un arrêt, déplacer un élément
# ou retirer un équipement change le Pareto, jamais les indicateurs.
def test_neutralite_element(base, arbre):
    inserer_production(base, JOUR_JUILLET)
    arret_id = inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"],
                             debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    avant = _indicateurs_du_jour(base)

    # Déplacer l'arrêt vers un autre élément.
    base.execute("UPDATE arret SET element_id = ? WHERE id = ?",
                 (arbre["machine3"], arret_id))
    base.commit()
    assert _indicateurs_du_jour(base) == avant

    # Déplacer un élément dans l'arbre.
    elements.deplacer_element(base, arbre["machine3"], arbre["zone1"])
    assert _indicateurs_du_jour(base) == avant

    # Retirer un équipement du service.
    elements.retirer_element(base, arbre["machine2"], "2026-08-01")
    assert _indicateurs_du_jour(base) == avant


# Invariant 19 — après retrait, les analyses passées restent identiques et les
# arrêts restent attribués à l'équipement retiré.
def test_retrait_non_destructif(base, arbre):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"],
                  debut="2026-07-15 08:00", fin="2026-07-15 08:47")
    pareto_avant = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="element")
    indicateurs_avant = _indicateurs_du_jour(base)

    elements.retirer_element(base, arbre["machine1"], "2026-08-01")

    assert _indicateurs_du_jour(base) == indicateurs_avant
    pareto_apres = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="element")
    assert pareto_apres.equals(pareto_avant)
    assert list(pareto_apres["libelle"]) == ["Machine 1"]
    # L'élément retiré n'est plus proposé à la saisie après sa date de fin...
    codes = [e["code"] for e in elements.elements_en_service(base, 1, "2026-08-15")]
    assert "MACH-1" not in codes
    # ... mais l'était encore à la date de l'arrêt.
    codes = [e["code"] for e in elements.elements_en_service(base, 1, JOUR_JUILLET)]
    assert "MACH-1" in codes


# Invariant 20 — suppression physique protégée, jamais de cascade.
def test_suppression_protegee(base, arbre):
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"], duree=10)
    with pytest.raises(SuppressionInterdite):
        elements.supprimer_element(base, arbre["machine1"])   # porte un arrêt
    with pytest.raises(SuppressionInterdite):
        elements.supprimer_element(base, arbre["zone1"])      # a des descendants
    # Un doublon sans arrêt ni descendant se supprime.
    doublon = elements.ajouter_element(base, 1, arbre["zone2"], "FAUTE", "Faute de frappe",
                                       "EQUIPEMENT", "2026-07-01")
    elements.supprimer_element(base, doublon)
    assert base.execute(
        "SELECT COUNT(*) FROM element_ligne WHERE id = ?", (doublon,)
    ).fetchone()[0] == 0


def test_remplacement_chaine_la_lignee(base, arbre):
    nouveau = elements.remplacer_element(
        base, arbre["machine1"], "MACH-1B", "Machine 1 nouvelle génération", "2026-08-01"
    )
    ancien = base.execute(
        "SELECT * FROM element_ligne WHERE id = ?", (arbre["machine1"],)
    ).fetchone()
    remplacant = base.execute(
        "SELECT * FROM element_ligne WHERE id = ?", (nouveau,)
    ).fetchone()
    assert ancien["date_fin"] == "2026-07-31"       # clôturé la veille
    assert remplacant["remplace_id"] == arbre["machine1"]
    assert remplacant["parent_id"] == ancien["parent_id"]
    assert remplacant["type"] == ancien["type"]


# Invariant 37 — après déplacement, le chemin de tous les descendants est à jour
# et l'agrégation par zone donne le même total qu'une somme élément par élément.
def test_deplacement_recalcule_les_chemins(base, arbre):
    organe = elements.ajouter_element(base, 1, arbre["machine1"], "ORG-1", "Organe 1",
                                      "ORGANE", "2026-01-01")
    elements.deplacer_element(base, arbre["machine1"], arbre["zone2"])
    chemin_machine = base.execute(
        "SELECT chemin FROM element_ligne WHERE id = ?", (arbre["machine1"],)
    ).fetchone()[0]
    chemin_organe = base.execute(
        "SELECT chemin FROM element_ligne WHERE id = ?", (organe,)
    ).fetchone()[0]
    assert chemin_machine == f"/{arbre['zone2']}/{arbre['machine1']}/"
    assert chemin_organe == f"/{arbre['zone2']}/{arbre['machine1']}/{organe}/"

    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=organe, duree=12)
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine3"], duree=8)
    par_zone = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="zone")
    par_element = arrets.pareto(base, 1, JOUR_JUILLET, JOUR_JUILLET, par="element")
    assert par_zone["duree_min"].sum() == par_element["duree_min"].sum() == 20
    assert dict(zip(par_zone["libelle"], par_zone["duree_min"])) == {"Zone 2": 20}


def test_deplacement_sous_un_descendant_refuse(base, arbre):
    with pytest.raises(ErreurMetier):
        elements.deplacer_element(base, arbre["zone1"], arbre["machine1"])


# Un retrait par erreur doit pouvoir être annulé : sans cela, un équipement
# retiré à tort est définitivement invisible, et le conseil « déplacez-le »
# devient inapplicable puisqu'il n'apparaît plus dans les listes de saisie.
def test_remise_en_service_apres_retrait(base, arbre):
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "PANNE", element_id=arbre["machine1"],
                  debut="2026-07-15 08:00", fin="2026-07-15 09:10")
    avant = _indicateurs_du_jour(base)

    elements.retirer_element(base, arbre["machine1"], "2026-08-01")
    assert "MACH-1" not in [
        e["code"] for e in elements.elements_en_service(base, 1, "2026-08-15")
    ]

    elements.remettre_en_service(base, arbre["machine1"], "Retrait par erreur", AUTEUR)
    assert "MACH-1" in [
        e["code"] for e in elements.elements_en_service(base, 1, "2026-08-15")
    ]
    # Les arrêts et les indicateurs sont intacts.
    assert _indicateurs_du_jour(base) == avant
    assert elements.nb_arrets(base, arbre["machine1"]) == 1
    # L'opération est tracée.
    assert base.execute(
        "SELECT COUNT(*) FROM journal_referentiel WHERE table_cible = 'element_ligne'"
        " AND action = 'CORRECTION'"
    ).fetchone()[0] >= 1


def test_remise_en_service_dun_element_deja_actif_refusee(base, arbre):
    with pytest.raises(ErreurMetier):
        elements.remettre_en_service(base, arbre["machine2"])
