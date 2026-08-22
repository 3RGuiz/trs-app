"""Produit un classeur Excel de contrôle du calcul du TRS.

Le cahier des charges (§13.4) demande deux semaines de double contrôle avant de
publier un premier chiffre : calculer à la main, en parallèle, et comparer. Ce
script fabrique le support de ce contrôle.

Le classeur ne contient aucune valeur calculée par l'application : **toutes les
cellules de résultat sont des formules Excel**, recalculées par Excel à partir
des données brutes. La colonne de comparaison montre côte à côte ce qu'Excel
trouve et ce que l'application affiche. Un écart signale soit un défaut de
l'application, soit — bien plus souvent — une donnée d'entrée à corriger.

Usage :
    .venv/bin/python generer_controle_trs.py --debut 2026-07-01 --fin 2026-07-31
    .venv/bin/python generer_controle_trs.py --ligne 1 --sortie controle.xlsx
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core import db, indicateurs, temps

# Couleurs sobres, cohérentes avec l'application.
ENTETE = PatternFill("solid", fgColor="1E1F1C")
SAISIE = PatternFill("solid", fgColor="FFF6D6")     # données venant de la base
FORMULE = PatternFill("solid", fgColor="E8F0FA")    # calculé par Excel
ECART = PatternFill("solid", fgColor="FDECEA")
BLANC = Font(color="FFFFFF", bold=True)
FILET = Border(*[Side(style="thin", color="D9D9D9")] * 4)


def _entete(feuille, ligne: int, valeurs: list[str], largeurs: list[int]) -> None:
    for numero, (titre, largeur) in enumerate(zip(valeurs, largeurs), start=1):
        cellule = feuille.cell(row=ligne, column=numero, value=titre)
        cellule.fill, cellule.font = ENTETE, BLANC
        cellule.alignment = Alignment(horizontal="center", vertical="center",
                                      wrap_text=True)
        feuille.column_dimensions[get_column_letter(numero)].width = largeur
    feuille.row_dimensions[ligne].height = 32


def feuille_mode_emploi(classeur: Workbook) -> None:
    feuille = classeur.create_sheet("Mode d'emploi", 0)
    feuille.column_dimensions["A"].width = 110
    textes = [
        ("Contrôle du calcul du TRS", True),
        ("", False),
        ("À quoi sert ce classeur", True),
        ("Vérifier que le TRS affiché par l'application est juste, en le "
         "recalculant indépendamment.", False),
        ("Toutes les cellules bleutées sont des FORMULES Excel : cliquez dessus "
         "pour voir le calcul.", False),
        ("Les cellules jaunes sont les données brutes extraites de la base de "
         "l'application.", False),
        ("", False),
        ("Comment l'utiliser", True),
        ("1. Ouvrez l'onglet « Contrôle journalier ».", False),
        ("2. Pour une journée, vérifiez les données brutes contre l'ERP et les "
         "relevés terrain : quantité produite, cadence de référence, temps "
         "d'ouverture, temps requis, minutes d'arrêt.", False),
        ("3. La colonne « Écart » compare le TRS recalculé par Excel à celui de "
         "l'application. Elle doit être nulle.", False),
        ("4. Un écart non nul vient presque toujours d'une donnée d'entrée : "
         "cadence mal renseignée, journée atypique non déclarée au calendrier, "
         "quantité en colis plutôt qu'en UVC.", False),
        ("", False),
        ("Les formules employées", True),
        ("Quantité produisible = cadence × temps requis", False),
        ("TRS = quantité produite ÷ quantité produisible   (identique à Tu ÷ Tr)", False),
        ("TRG = quantité produite ÷ (cadence × temps d'ouverture)", False),
        ("TRE = quantité produite ÷ (cadence × 1440 minutes)", False),
        ("Temps utile Tu = quantité produite ÷ cadence   (en minutes)", False),
        ("Temps de fonctionnement Tf = temps requis − arrêts propres", False),
        ("", False),
        ("Ce que ce classeur ne vérifie pas", True),
        ("Les journées où plusieurs cadences coexistent : le contrôle suppose "
         "une cadence unique par jour. Les journées concernées portent la "
         "mention « cadences multiples » et sont à vérifier autrement.", False),
        ("L'exactitude des données d'entrée elles-mêmes : c'est justement ce "
         "que vous confrontez au terrain.", False),
    ]
    for numero, (texte, gras) in enumerate(textes, start=1):
        cellule = feuille.cell(row=numero, column=1, value=texte)
        cellule.font = Font(bold=gras, size=13 if gras and numero == 1 else 11)
        cellule.alignment = Alignment(wrap_text=True, vertical="top")


def feuille_controle(classeur: Workbook, cascade, unite: str) -> None:
    feuille = classeur.create_sheet("Contrôle journalier")
    colonnes = [
        "Jour", "État", "Quantité produite\n(" + unite + ")",
        "Cadence\n(" + unite + "/min)", "Temps ouverture\n(min)",
        "Temps requis\n(min)", "Arrêts propres\n(min)",
        "Produisible\n= cadence × Tr", "Tu\n= qté ÷ cadence", "Tf\n= Tr − arrêts",
        "TRS Excel\n= qté ÷ produisible", "TRG Excel", "TRE Excel",
        "TRS application", "Écart",
    ]
    _entete(feuille, 1, colonnes,
            [12, 20, 14, 12, 12, 12, 12, 14, 12, 12, 14, 11, 11, 14, 10])

    ligne = 2
    for _, jour in cascade.iterrows():
        if jour["etat"] not in ("OK",):
            continue
        # Une cadence unique est nécessaire pour recalculer à la main.
        cadence = (jour["qte_produisible_tr"] / jour["Tr"]
                   if jour["qte_produisible_tr"] and jour["Tr"] else None)
        trs_app = jour["Tu"] / jour["Tr"] if jour["Tr"] else None

        feuille.cell(row=ligne, column=1, value=jour["date"]).number_format = "DD/MM/YYYY"
        feuille.cell(row=ligne, column=2,
                     value="cadences multiples" if cadence is None else "vérifiable")
        for colonne, valeur in (
            (3, float(jour["qte_produite"])), (4, cadence),
            (5, float(jour["To"])), (6, float(jour["Tr"])),
            (7, float(jour["arrets_propres_min"])),
        ):
            cellule = feuille.cell(row=ligne, column=colonne, value=valeur)
            cellule.fill = SAISIE
            cellule.border = FILET

        # Formules Excel : c'est le cœur du contrôle, rien n'est pré-calculé.
        for colonne, formule, format_nombre in (
            (8, f"=D{ligne}*F{ligne}", "#,##0"),
            (9, f"=IF(D{ligne}=0,\"\",C{ligne}/D{ligne})", "#,##0.0"),
            (10, f"=F{ligne}-G{ligne}", "#,##0"),
            (11, f"=IF(H{ligne}=0,\"\",C{ligne}/H{ligne})", "0.0%"),
            (12, f"=IF(E{ligne}=0,\"\",C{ligne}/(D{ligne}*E{ligne}))", "0.0%"),
            (13, f"=IF(D{ligne}=0,\"\",C{ligne}/(D{ligne}*1440))", "0.0%"),
        ):
            cellule = feuille.cell(row=ligne, column=colonne, value=formule)
            cellule.fill, cellule.number_format, cellule.border = FORMULE, format_nombre, FILET

        cellule = feuille.cell(row=ligne, column=14, value=trs_app)
        cellule.number_format, cellule.border = "0.0%", FILET
        cellule = feuille.cell(row=ligne, column=15,
                               value=f"=IF(K{ligne}=\"\",\"\",K{ligne}-N{ligne})")
        cellule.fill, cellule.number_format, cellule.border = ECART, "0.00%", FILET
        ligne += 1

    if ligne == 2:
        feuille.cell(row=2, column=1,
                     value="Aucune journée exploitable sur la période demandée.")
        return

    # Totaux : on somme les temps, puis on divise — jamais l'inverse (CDC §5.3).
    derniere = ligne - 1
    feuille.cell(row=ligne + 1, column=1, value="TOTAL période").font = Font(bold=True)
    feuille.cell(row=ligne + 1, column=2,
                 value="somme des temps, PUIS ratio").font = Font(italic=True)
    for colonne in (3, 8, 9, 10):
        lettre = get_column_letter(colonne)
        cellule = feuille.cell(row=ligne + 1, column=colonne,
                               value=f"=SUM({lettre}2:{lettre}{derniere})")
        cellule.font, cellule.number_format = Font(bold=True), "#,##0"
    cellule = feuille.cell(row=ligne + 1, column=11,
                           value=f"=IF(H{ligne + 1}=0,\"\",C{ligne + 1}/H{ligne + 1})")
    cellule.font, cellule.number_format, cellule.fill = Font(bold=True), "0.0%", FORMULE
    feuille.cell(row=ligne + 3, column=1,
                 value="Attention : la moyenne des TRS journaliers ne donne PAS le TRS "
                       "de la période. Il faut sommer les temps, puis diviser.").font = (
        Font(italic=True, color="B00000"))
    feuille.freeze_panes = "A2"


def feuille_reference(classeur: Workbook) -> None:
    """Cas de référence du cahier des charges, pour valider le classeur lui-même."""
    feuille = classeur.create_sheet("Cas de référence")
    feuille.column_dimensions["A"].width = 46
    feuille.column_dimensions["B"].width = 18
    feuille.column_dimensions["C"].width = 46
    feuille.cell(row=1, column=1, value="Cas de référence du cahier des charges").font = (
        Font(bold=True, size=13))
    feuille.cell(row=2, column=1,
                 value="Si ces trois résultats tombent juste, les formules du classeur "
                       "sont bonnes.").font = Font(italic=True)
    donnees = [
        ("Cadence de référence (UVC/min)", 30, "donnée"),
        ("Temps d'ouverture To (min)", 840, "donnée"),
        ("Temps requis Tr (min)", 570, "donnée"),
        ("Temps total Tt (min)", 1440, "donnée"),
        ("Quantité produite (UVC)", 13200, "donnée"),
    ]
    ligne = 4
    for libelle, valeur, _ in donnees:
        feuille.cell(row=ligne, column=1, value=libelle)
        cellule = feuille.cell(row=ligne, column=2, value=valeur)
        cellule.fill = SAISIE
        ligne += 1

    attendus = [
        ("Quantité produisible sur Tr", "=B4*B6", "#,##0", "17 100 attendus"),
        ("Temps utile Tu (min)", "=B8/B4", "#,##0.0", "440,0 attendues"),
        ("TRS", "=B8/B10", "0.00%", "77,19 % attendus"),
        ("TRG", "=B8/(B4*B5)", "0.00%", "52,38 % attendus"),
        ("TRE", "=B8/(B4*B7)", "0.00%", "30,56 % attendus"),
    ]
    ligne += 1
    for libelle, formule, format_nombre, attendu in attendus:
        feuille.cell(row=ligne, column=1, value=libelle).font = Font(bold=True)
        cellule = feuille.cell(row=ligne, column=2, value=formule)
        cellule.fill, cellule.number_format, cellule.font = FORMULE, format_nombre, Font(bold=True)
        feuille.cell(row=ligne, column=3, value=attendu).font = Font(italic=True)
        ligne += 1


def generer(chemin_base: Path, ligne_id: int, debut: date, fin: date,
            sortie: Path) -> Path:
    conn = db.ouvrir_connexion(chemin_base)
    try:
        libelle = conn.execute(
            "SELECT libelle FROM ligne WHERE id = ?", (ligne_id,)
        ).fetchone()
        if libelle is None:
            raise SystemExit(f"La ligne n° {ligne_id} n'existe pas dans {chemin_base}.")
        unite = "UVC"
        if "(" in libelle[0] and ")" in libelle[0]:
            unite = libelle[0].rsplit("(", 1)[1].split(")")[0].strip() or "UVC"
        cascade = temps.cascade_journaliere(conn, ligne_id, debut, fin)
        resultat = indicateurs.indicateurs_periode(cascade)
    finally:
        conn.close()

    classeur = Workbook()
    classeur.remove(classeur.active)
    feuille_mode_emploi(classeur)
    feuille_controle(classeur, cascade, unite)
    feuille_reference(classeur)
    classeur.save(sortie)

    exploitables = int((cascade["etat"] == "OK").sum())
    trs = resultat["TRS"]
    print(f"Classeur écrit : {sortie}")
    print(f"  ligne « {libelle[0]} », du {debut} au {fin}")
    print(f"  {exploitables} journée(s) exploitable(s) à contrôler")
    print(f"  TRS de la période selon l'application : "
          f"{'non mesuré' if trs is None else f'{trs:.2%}'}")
    return sortie


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--base", type=Path, default=Path("data/trs.db"))
    parseur.add_argument("--ligne", type=int, default=1)
    parseur.add_argument("--debut", type=date.fromisoformat)
    parseur.add_argument("--fin", type=date.fromisoformat)
    parseur.add_argument("--sortie", type=Path,
                         default=Path("data/controle_trs.xlsx"))
    options = parseur.parse_args()

    if not options.base.exists():
        print(f"Base introuvable : {options.base}")
        return 1
    conn = db.ouvrir_connexion(options.base)
    bornes = conn.execute(
        "SELECT MIN(date), MAX(date) FROM production WHERE ligne_id = ?",
        (options.ligne,),
    ).fetchone()
    conn.close()
    if bornes[0] is None:
        print("Aucune production enregistrée pour cette ligne.")
        return 1

    debut = options.debut or date.fromisoformat(bornes[0])
    fin = options.fin or date.fromisoformat(bornes[1])
    options.sortie.parent.mkdir(parents=True, exist_ok=True)
    generer(options.base, options.ligne, debut, fin, options.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
