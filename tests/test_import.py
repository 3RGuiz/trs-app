"""Import ERP — invariants 7, 29 à 34 du CDC §5.5."""

from __future__ import annotations

from datetime import date

import openpyxl
import pandas as pd
import pytest

from core import db, importer
from core.erreurs import ConfirmationRequise, ImportInvalide, ValeurNonConvertible
from tests.conftest import AUTEUR


def _df(*lignes) -> pd.DataFrame:
    """DataFrame normalisé : (date, article, of, planifiée, produite[, ensachée])."""
    colonnes = ["date", "article_code", "of_numero",
                "qte_planifiee", "qte_produite", "qte_ensachee"]
    complettees = [list(l) + [None] * (6 - len(l)) for l in lignes]
    return pd.DataFrame(complettees, columns=colonnes)


def _chemin_db(conn):
    return conn.execute("PRAGMA database_list").fetchone()[2]


def _production(conn) -> list[tuple]:
    return conn.execute(
        "SELECT date, article_code, of_numero, qte_planifiee, qte_produite, qte_ensachee"
        " FROM production ORDER BY date, article_code, of_numero"
    ).fetchall()


# Invariant 7 — idempotence : importer deux fois le même fichier ne double rien.
def test_idempotence(base):
    df = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200),
             (date(2026, 7, 14), "ART-002", "OF-2", 10_000, 9_000))
    importer.importer_production(base, _chemin_db(base), df, 1, empreinte="e1")
    avant = _production(base)
    importer.importer_production(base, _chemin_db(base), df, 1,
                                 empreinte="e1", confirmer_reimport=True)
    assert _production(base) == avant
    assert len(avant) == 2


# Invariant 29 — modes d'écriture : le remplacement supprime une ligne absente du
# fichier sur la période couverte, l'upsert la conserve. L'aperçu annonce
# exactement les compteurs constatés après écriture.
def test_modes_d_ecriture(base):
    initial = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200),
                  (date(2026, 7, 14), "ART-002", "OF-2", 10_000, 9_000),
                  (date(2026, 7, 15), "ART-003", "OF-3", 8_000, 7_500))
    importer.importer_production(base, _chemin_db(base), initial, 1)

    # Le nouveau fichier couvre la même période mais ne contient plus OF-2.
    correctif = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_400),
                    (date(2026, 7, 15), "ART-003", "OF-3", 8_000, 7_500))

    # Mode UPSERT : la ligne absente est conservée.
    apercu = importer.apercu_differences(base, correctif, 1, mode="UPSERT")
    assert (apercu["nb_ajouts"], apercu["nb_maj"], apercu["nb_suppressions"]) == (0, 1, 0)
    rapport = importer.importer_production(base, _chemin_db(base), correctif, 1, mode="UPSERT")
    assert (rapport["nb_ajouts"], rapport["nb_maj"], rapport["nb_suppressions"]) == (0, 1, 0)
    assert len(_production(base)) == 3

    # Mode REMPLACEMENT_PERIODE : la ligne absente disparaît (avec confirmation,
    # car 1 suppression sur 3 dépasse le seuil de 10 %).
    apercu = importer.apercu_differences(base, correctif, 1, mode="REMPLACEMENT_PERIODE")
    assert apercu["nb_suppressions"] == 1
    rapport = importer.importer_production(
        base, _chemin_db(base), correctif, 1, mode="REMPLACEMENT_PERIODE",
        confirmer_suppressions=True,
    )
    assert rapport["nb_suppressions"] == 1
    restants = _production(base)
    assert len(restants) == 2
    assert all(l["of_numero"] != "OF-2" for l in restants)


# Invariant 30 — annulation : la base revient strictement à son état d'avant
# l'import, y compris pour les lignes écrasées par un upsert.
def test_annulation_d_import(base, tmp_path):
    chemin = _chemin_db(base)
    premier = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200))
    importer.importer_production(base, chemin, premier, 1)
    etat_avant = [tuple(l) for l in _production(base)]

    ecrasement = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 99_999),
                     (date(2026, 7, 14), "ART-002", "OF-2", 5_000, 4_000))
    importer.importer_production(base, chemin, ecrasement, 1)
    assert [tuple(l) for l in _production(base)] != etat_avant

    base.close()
    importer.annuler_dernier_import(chemin)
    reprise = db.ouvrir_connexion(chemin)
    try:
        etat_apres = [tuple(l) for l in reprise.execute(
            "SELECT date, article_code, of_numero, qte_planifiee, qte_produite,"
            " qte_ensachee FROM production ORDER BY date, article_code, of_numero"
        ).fetchall()]
        assert etat_apres == etat_avant
    finally:
        reprise.close()


# Invariant 31 — un fichier de même empreinte est reconnu et signalé ; un fichier
# corrigé de même période met à jour sans dupliquer.
def test_detection_de_reimport(base):
    df = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200))
    importer.importer_production(base, _chemin_db(base), df, 1, empreinte="abc")

    apercu = importer.apercu_differences(base, df, 1, empreinte="abc")
    assert apercu["deja_importe"] is not None
    with pytest.raises(ConfirmationRequise):
        importer.importer_production(base, _chemin_db(base), df, 1, empreinte="abc")

    corrige = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_500))
    importer.importer_production(base, _chemin_db(base), corrige, 1, empreinte="def")
    lignes = _production(base)
    assert len(lignes) == 1
    assert lignes[0]["qte_produite"] == 13_500


# Invariant 32 — CSV Windows français : cp1252, point-virgule, virgule décimale,
# espaces insécables. Les quantités sont numériques et la somme est juste.
def test_csv_windows_francais(base, tmp_path):
    contenu = (
        "Date;Article;OF;Quantite planifiee;Quantite produite\r\n"
        "13/07/2026;ART-001;OF-1;15\xa0000;5\xa0400,25\r\n"
        "14/07/2026;ART-002;OF-2;10\xa0000;5\xa0950,75\r\n"
    )
    fichier = tmp_path / "export_windows.csv"
    fichier.write_bytes(contenu.encode("cp1252"))

    brut, profil = importer.lire_fichier(fichier)
    assert profil["encodage"] == "cp1252"
    assert profil["separateur"] == ";"

    mapping = {"date": "Date", "article_code": "Article", "of_numero": "OF",
               "qte_planifiee": "Quantite planifiee", "qte_produite": "Quantite produite"}
    normalise = importer.normaliser(brut, mapping)
    assert pd.api.types.is_numeric_dtype(normalise["qte_produite"])
    assert normalise["qte_produite"].sum() == pytest.approx(11_351.0)
    assert normalise["date"].iloc[0] == date(2026, 7, 13)

    # Une valeur non convertible arrête l'import, jamais de NaN silencieux.
    fichier_faux = tmp_path / "export_faux.csv"
    fichier_faux.write_bytes(
        "Date;Article;OF;Quantite planifiee;Quantite produite\r\n"
        "13/07/2026;ART-001;OF-1;15000;n/d\r\n".encode("cp1252")
    )
    brut_faux, _ = importer.lire_fichier(fichier_faux)
    with pytest.raises(ValeurNonConvertible):
        importer.normaliser(brut_faux, mapping)


# Invariant 33 — fenêtre de rafraîchissement : un export cumulatif ne modifie que
# les N derniers jours ; une suppression massive est bloquée sans confirmation.
def test_fenetre_de_rafraichissement(base):
    ancienne = _df((date(2026, 6, 2), "ART-001", "OF-VIEUX", 10_000, 8_000))
    recente = _df((date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200))
    importer.importer_production(base, _chemin_db(base), ancienne, 1)
    importer.importer_production(base, _chemin_db(base), recente, 1)

    # Export cumulatif : il couvre juin et juillet mais ne contient plus OF-VIEUX,
    # et modifie la ligne de juin. Avec une fenêtre de 30 jours, juin est figé.
    cumulatif = _df((date(2026, 6, 2), "ART-001", "OF-VIEUX", 10_000, 1),
                    (date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_400),
                    (date(2026, 7, 14), "ART-002", "OF-2", 9_000, 8_500))
    rapport = importer.importer_production(
        base, _chemin_db(base), cumulatif, 1,
        mode="REMPLACEMENT_PERIODE", fenetre_jours=30,
    )
    assert rapport["nb_hors_fenetre"] == 1
    vieux = base.execute(
        "SELECT qte_produite FROM production WHERE of_numero = 'OF-VIEUX'"
    ).fetchone()
    assert vieux[0] == 8_000          # la ligne hors fenêtre n'a pas bougé

    # Suppression massive : un export tronqué qui couvre les 13-14/07 mais a
    # perdu OF-1 supprimerait 1 ligne sur 2 (> 10 %) — bloqué sans confirmation.
    tronque = _df((date(2026, 7, 13), "ART-003", "OF-9", 5_000, 4_000),
                  (date(2026, 7, 14), "ART-002", "OF-2", 9_000, 8_500))
    with pytest.raises(ConfirmationRequise):
        importer.importer_production(
            base, _chemin_db(base), tronque, 1,
            mode="REMPLACEMENT_PERIODE", fenetre_jours=30,
        )


# Invariant 34 — classeur .xlsx piégé : titre en première ligne, ligne vide,
# nombres stockés en texte, colonne de formules non évaluées, feuille parasite.
def test_xlsx_piege(base, tmp_path):
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "Production"
    feuille.append(["Extraction du 21/08/2026"])
    feuille.append([])
    feuille.append(["Date", "Article", "OF", "Quantite planifiee",
                    "Quantite produite", "Total"])
    feuille.append(["13/07/2026", "ART-001", "OF-1", "15 000", "13 200", "=E4*2"])
    feuille.append(["14/07/2026", "ART-002", "OF-2", "10 000", "9 000,5", "=E5*2"])
    classeur.create_sheet("Parametres parasites")
    fichier = tmp_path / "extraction_piege.xlsx"
    classeur.save(fichier)

    brut, profil = importer.lire_fichier(fichier)
    assert profil["entete_ligne"] == 2          # titre + ligne vide détectés
    assert "Date" in brut.columns

    mapping = {"date": "Date", "article_code": "Article", "of_numero": "OF",
               "qte_planifiee": "Quantite planifiee", "qte_produite": "Quantite produite"}
    normalise = importer.normaliser(brut, mapping, profil)
    assert pd.api.types.is_numeric_dtype(normalise["qte_produite"])
    assert normalise["qte_produite"].sum() == pytest.approx(22_200.5)

    # La colonne de formules jamais évaluées est signalée vide, pas importée à zéro.
    with pytest.raises(ImportInvalide, match="formules"):
        importer.normaliser(brut, {**mapping, "qte_ensachee": "Total"}, profil)


def test_article_inconnu_cree_en_famille_a_classer(base):
    df = _df((date(2026, 7, 13), "ART-NOUVEAU", "OF-1", 1_000, 900))
    rapport = importer.importer_production(base, _chemin_db(base), df, 1)
    assert rapport["articles_inconnus_crees"] == ["ART-NOUVEAU"]
    famille = base.execute(
        "SELECT f.libelle FROM article_famille af JOIN famille f ON f.id = af.famille_id"
        " WHERE af.article_code = 'ART-NOUVEAU'"
    ).fetchone()
    assert famille[0] == "À classer"
    assert rapport["sans_cadence"] == [("ART-NOUVEAU", "2026-07-13")]


def test_rejets_et_controles(base):
    df = _df(
        (date(2026, 7, 13), "ART-001", "OF-1", 15_000, 13_200),
        (date(2026, 7, 13), "ART-002", "OF-2", 10_000, -50),            # négatif
        (date(2026, 7, 13), "ART-003", "OF-3", 8_000, 9_000, 8_500),    # produite > ensachée
        (None, "ART-001", "OF-4", 1_000, 900),                          # date absente
    )
    rapport = importer.importer_production(base, _chemin_db(base), df, 1)
    assert rapport["nb_rejets"] == 3
    assert rapport["nb_ajouts"] == 1
    assert len(_production(base)) == 1


def test_depassement_de_produisible_signale(base):
    # 30 ppm x 570 min = 17 100 produisibles : 18 000 doit déclencher une anomalie.
    df = _df((date(2026, 7, 13), "ART-001", "OF-1", 20_000, 18_000))
    rapport = importer.importer_production(base, _chemin_db(base), df, 1)
    assert any("produisible" in a for a in rapport["anomalies"])
