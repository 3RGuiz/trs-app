"""Catalogue de motifs — invariants 21, 22, 23 et refus des motifs de sous-cadence."""

from __future__ import annotations

import pytest

from core import db, indicateurs, motifs, temps
from core.erreurs import MotifInterdit, SuppressionInterdite
from tests.conftest import AUTEUR, JOUR_JUILLET, inserer_arret, inserer_production, motif_id


def test_onze_motifs_generiques_livres(conn):
    assert conn.execute("SELECT COUNT(*) FROM motif_arret").fetchone()[0] == len(
        db.MOTIFS_AYEL_DAVIER
    ) == 11
    globaux = conn.execute(
        "SELECT COUNT(*) FROM motif_element WHERE element_id IS NULL"
    ).fetchone()[0]
    assert globaux == 11


# Invariant 21 — héritage de la liste le long de l'arborescence.
def test_liste_de_motifs_heritee(base, arbre):
    bourrage_zone = motifs.creer_motif(
        base, "BOURRAGE-Z1", "Bourrage", "ARRET_PROPRE", "2026-06-01",
        "Motif de zone", AUTEUR, element_id=arbre["zone1"],
    )
    capteur_machine = motifs.creer_motif(
        base, "CAPTEUR-M3", "Capteur défaillant", "ARRET_PROPRE", "2026-06-01",
        "Motif d'équipement", AUTEUR, element_id=arbre["machine3"],
    )
    # Sur Machine 1 (fille de Zone 1) : le motif de zone est proposé, pas celui
    # de Machine 3 ; les motifs globaux sont proposés partout.
    proposes = {m["id"] for m in motifs.motifs_proposes(base, arbre["machine1"], JOUR_JUILLET)}
    assert bourrage_zone in proposes
    assert capteur_machine not in proposes
    assert motif_id(base, "PANNE") in proposes

    # Sur Machine 3 : son motif propre plus les globaux, pas celui de Zone 1.
    proposes = {m["id"] for m in motifs.motifs_proposes(base, arbre["machine3"], JOUR_JUILLET)}
    assert capteur_machine in proposes
    assert bourrage_zone not in proposes

    # Un motif retiré n'est plus proposé mais reste lisible sur les arrêts passés.
    arret_id = inserer_arret(base, JOUR_JUILLET, "BOURRAGE-Z1",
                             element_id=arbre["machine1"], duree=10)
    motifs.retirer_motif(base, bourrage_zone, "2026-08-01", "Motif retiré", AUTEUR)
    proposes = {m["id"] for m in motifs.motifs_proposes(base, arbre["machine1"], "2026-08-15")}
    assert bourrage_zone not in proposes
    assert base.execute(
        "SELECT motif_id FROM arret WHERE id = ?", (arret_id,)
    ).fetchone()[0] == bourrage_zone


def test_refus_motif_sous_cadence(base):
    for libelle in ("Sous-cadence", "Bridage conditionnement", "Ligne ralentie"):
        with pytest.raises(MotifInterdit):
            motifs.creer_motif(base, f"X-{libelle[:6]}", libelle, "ARRET_PROPRE",
                               "2026-06-01", "Tentative", AUTEUR)
    # La sous-charge (pas assez de commandes), elle, est légitime.
    motifs.verifier_libelle("Sous-charge")


def test_detection_libelles_proches(base, arbre):
    motifs.creer_motif(base, "BOURRAGE", "Bourrage", "ARRET_PROPRE", "2026-06-01",
                       "Création", AUTEUR, element_id=arbre["zone1"])
    proches = motifs.libelles_proches(base, "bourage")   # faute de frappe
    assert any(m["code"] == "BOURRAGE" for m in proches)
    assert not any(m["code"] == "NETTOYAGE" for m in motifs.libelles_proches(base, "bourage"))


# Invariant 23 — fusion de doublons : les temps se conservent, la cascade ne bouge pas.
def test_fusion_de_doublons(base, arbre):
    original = motifs.creer_motif(base, "BOURRAGE", "Bourrage", "ARRET_PROPRE",
                                  "2026-06-01", "Création", AUTEUR, element_id=arbre["zone1"])
    doublon = motifs.creer_motif(base, "BOURAGE", "Bourage", "ARRET_PROPRE",
                                 "2026-06-01", "Doublon involontaire", AUTEUR,
                                 element_id=arbre["zone1"])
    inserer_production(base, JOUR_JUILLET)
    inserer_arret(base, JOUR_JUILLET, "BOURRAGE", element_id=arbre["machine1"],
                  debut="2026-07-15 08:00", fin="2026-07-15 08:30")
    inserer_arret(base, JOUR_JUILLET, "BOURAGE", element_id=arbre["machine2"],
                  debut="2026-07-15 09:00", fin="2026-07-15 09:20")

    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    avant = indicateurs.indicateurs_periode(df)

    reaffectes = motifs.fusionner_motifs(base, original, doublon,
                                         "Fusion de doublons", AUTEUR)
    assert reaffectes == 1
    duree_totale = base.execute(
        "SELECT SUM(duree_min) FROM arret WHERE motif_id = ?", (original,)
    ).fetchone()[0]
    assert duree_totale == 50            # 30 + 20 : la somme des deux motifs d'origine

    df = temps.cascade_journaliere(base, 1, JOUR_JUILLET, JOUR_JUILLET)
    apres = indicateurs.indicateurs_periode(df)
    for cle in ("TRS", "TRG", "TRE", "DO", "TP", "Tf"):
        assert apres[cle] == avant[cle]


def test_suppression_motif_protegee(base):
    panne = motif_id(base, "PANNE")
    inserer_arret(base, JOUR_JUILLET, "PANNE", duree=5)
    with pytest.raises(SuppressionInterdite):
        motifs.supprimer_motif(base, panne)
