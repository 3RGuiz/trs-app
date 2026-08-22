"""Navigation dans la composition de la ligne, par dévoilement progressif.

Une liste à plat de quarante équipements oblige à tout lire pour trouver une
machine. Les zones étant le découpage que les gens de la ligne ont en tête, on
montre d'abord les zones seules, et le contenu n'apparaît qu'au clic.

Deux règles tenues ici, tirées des usages établis :
- **jamais plus de trois niveaux** de dévoilement ; au-delà, c'est le découpage
  qu'il faut revoir, pas l'interface ;
- **choisir se fait par étapes** : la zone d'abord, l'équipement ensuite. Sur un
  écran de saisie d'arrêt, cela divise par dix le nombre d'options à lire.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import streamlit as st

from core import elements
from core.db import iso

LIBELLES_TYPE = {"ZONE": "Zone", "EQUIPEMENT": "Équipement", "ORGANE": "Organe"}


def _elements_de_la_ligne(
    conn: sqlite3.Connection, ligne_id: int, jour: date | str | None,
    inclure_retires: bool,
) -> list[dict]:
    if jour is not None and not inclure_retires:
        return elements.elements_en_service(conn, ligne_id, jour)
    requete = "SELECT * FROM element_ligne WHERE ligne_id = ?"
    parametres: list = [ligne_id]
    if not inclure_retires:
        requete += " AND date_fin IS NULL"
    lignes = conn.execute(requete + " ORDER BY chemin, ordre", parametres).fetchall()
    return [dict(l) for l in lignes]


def grouper_par_zone(
    conn: sqlite3.Connection, ligne_id: int, jour: date | str | None = None,
    inclure_retires: bool = False,
) -> tuple[list[dict], dict[int, list[dict]], list[dict]]:
    """(zones, contenu par zone, éléments hors zone).

    Les éléments sans zone parente sont retournés à part plutôt que masqués :
    c'est précisément l'oubli de rattachement qu'on veut rendre visible.
    """
    tous = _elements_de_la_ligne(conn, ligne_id, jour, inclure_retires)
    par_identifiant = {e["id"]: e for e in tous}

    zones = [e for e in tous if e["parent_id"] is None and e["type"] == "ZONE"]
    identifiants_zones = {z["id"] for z in zones}

    contenu: dict[int, list[dict]] = {z["id"]: [] for z in zones}
    hors_zone: list[dict] = []
    for element in tous:
        if element["id"] in identifiants_zones:
            continue
        racine = element["chemin"].strip("/").split("/")[0]
        racine = int(racine) if racine.isdigit() else None
        if racine in contenu and racine != element["id"]:
            contenu[racine].append(element)
        elif element["parent_id"] is None or racine not in par_identifiant:
            hors_zone.append(element)
        else:
            hors_zone.append(element)
    return zones, contenu, hors_zone


def afficher_arbre(
    conn: sqlite3.Connection, ligne_id: int, jour: date | str | None = None,
    inclure_retires: bool = False, avec_arrets: bool = True,
) -> None:
    """Vue dépliable : les zones seules, leur contenu au clic."""
    zones, contenu, hors_zone = grouper_par_zone(conn, ligne_id, jour, inclure_retires)

    if not zones and not hors_zone:
        st.info(
            "Aucun élément déclaré. Commencez par créer les zones — cuisson, "
            "ensachage, utilités — puis rattachez-y les équipements."
        )
        return

    if hors_zone:
        st.warning(
            f"{len(hors_zone)} élément(s) ne sont rattachés à aucune zone : "
            + ", ".join(f"« {e['libelle']} »" for e in hors_zone[:4])
            + (", …" if len(hors_zone) > 4 else "")
            + ". Ils apparaîtront sous « Origine non renseignée » dans le Pareto "
            "par zone. Utilisez « Déplacer » pour les rattacher."
        )

    for zone in zones:
        enfants = contenu.get(zone["id"], [])
        arrets_zone = sum(elements.nb_arrets(conn, e["id"]) for e in enfants) if avec_arrets else 0
        resume = f"{len(enfants)} équipement(s)"
        if avec_arrets and arrets_zone:
            resume += f" · {arrets_zone} arrêt(s)"
        with st.expander(f"**{zone['libelle']}** — {resume}"):
            if not enfants:
                st.caption("Aucun équipement dans cette zone.")
                continue
            lignes = []
            for element in enfants:
                profondeur = element["chemin"].strip("/").count("/") - 1
                lignes.append({
                    "Élément": ("   " * max(0, profondeur)) + element["libelle"],
                    "Type": LIBELLES_TYPE.get(element["type"], element["type"]),
                    "En service depuis": element["date_debut"],
                    "Retiré le": element["date_fin"] or "",
                    "Arrêts": elements.nb_arrets(conn, element["id"]) if avec_arrets else "",
                })
            st.dataframe(lignes, width="stretch", hide_index=True)

    if hors_zone:
        with st.expander(f"**Hors zone** — {len(hors_zone)} élément(s) à rattacher"):
            st.dataframe(
                [{"Élément": e["libelle"],
                  "Type": LIBELLES_TYPE.get(e["type"], e["type"]),
                  "En service depuis": e["date_debut"],
                  "Arrêts": elements.nb_arrets(conn, e["id"]) if avec_arrets else ""}
                 for e in hors_zone],
                width="stretch", hide_index=True,
            )


RETRAIT = " " * 6      # indentation d'un niveau, en espaces insécables


def options_hierarchiques(
    conn: sqlite3.Connection,
    ligne_id: int,
    jour: date | str | None = None,
    inclure_retires: bool = False,
) -> tuple[list[int], dict[int, str]]:
    """Une seule liste, ordonnée et indentée, plutôt que deux menus enchaînés.

    Retourne les identifiants dans l'ordre de l'arbre et leur libellé d'affichage :

        ZONE : Friture
              Friteuse conv
              Friteuse batch
        ZONE : Enrobage
              Tunnel d'enrobage

    La hiérarchie se lit d'un coup d'œil sans qu'il faille ouvrir une zone pour
    savoir ce qu'elle contient.
    """
    zones, contenu, hors_zone = grouper_par_zone(conn, ligne_id, jour, inclure_retires)
    ordre: list[int] = []
    libelles: dict[int, str] = {}

    def _suffixe(element: dict) -> str:
        return f"  (retiré le {element['date_fin']})" if element["date_fin"] else ""

    for zone in zones:
        ordre.append(zone["id"])
        libelles[zone["id"]] = f"ZONE : {zone['libelle']}{_suffixe(zone)}"
        for element in contenu.get(zone["id"], []):
            profondeur = max(1, element["chemin"].strip("/").count("/"))
            ordre.append(element["id"])
            libelles[element["id"]] = (
                RETRAIT * profondeur + element["libelle"] + _suffixe(element)
            )
    for element in hors_zone:
        ordre.append(element["id"])
        libelles[element["id"]] = f"(hors zone) {element['libelle']}{_suffixe(element)}"
    return ordre, libelles


def selecteur_element(
    conn: sqlite3.Connection,
    ligne_id: int,
    jour: date | str | None = None,
    cle: str = "element",
    libelle: str = "Élément",
    autoriser_aucun: bool = True,
    autoriser_zone: bool = True,
    aide: str | None = None,
) -> int | None:
    """Choix d'un élément dans une liste unique, hiérarchie visible."""
    ordre, libelles = options_hierarchiques(conn, ligne_id, jour)
    if not autoriser_zone:
        zones = {
            identifiant for identifiant, texte in libelles.items()
            if texte.startswith("ZONE : ")
        }
        ordre = [identifiant for identifiant in ordre if identifiant not in zones]
    if not ordre:
        st.caption("Aucun élément en service à cette date.")
        return None

    options: list[int | None] = list(ordre)
    if autoriser_aucun:
        options.insert(0, None)
        libelles[None] = "Origine non renseignée"

    return st.selectbox(
        libelle, options, format_func=lambda i: libelles.get(i, str(i)),
        key=f"{cle}_choix", help=aide,
    )


def destinations_possibles(
    conn: sqlite3.Connection, ligne_id: int, element_id: int
) -> tuple[list[int | None], dict[int | None, str]]:
    """Où un élément peut être rattaché, selon ce qu'il est.

    Un organe se rattache à un équipement, un équipement à une zone, une zone à
    la racine. Proposer les zones comme destination d'un organe n'aurait pas de
    sens, et proposer un équipement comme parent d'une zone non plus.
    """
    element = conn.execute(
        "SELECT type, chemin FROM element_ligne WHERE id = ?", (element_id,)
    ).fetchone()
    if element is None:
        return [], {}

    ordre, libelles = options_hierarchiques(conn, ligne_id)
    interdits = {element_id}
    # Ni l'élément lui-même, ni l'un de ses descendants.
    for candidat in conn.execute(
        "SELECT id FROM element_ligne WHERE ligne_id = ? AND chemin LIKE ?",
        (ligne_id, element["chemin"] + "%"),
    ):
        interdits.add(candidat[0])

    types = {
        identifiant[0]: identifiant[1] for identifiant in conn.execute(
            "SELECT id, type FROM element_ligne WHERE ligne_id = ?", (ligne_id,))
    }
    attendu = {"ORGANE": "EQUIPEMENT", "EQUIPEMENT": "ZONE"}.get(element["type"])

    if element["type"] == "ZONE":
        # Une zone est un niveau racine : elle ne se range pas sous un
        # équipement, et la ranger sous une autre zone ferait un quatrième
        # niveau que l'arborescence n'a pas vocation à porter.
        libelles[None] = "Racine — zone de premier niveau"
        return [None], libelles

    options: list[int | None] = [
        identifiant for identifiant in ordre
        if identifiant not in interdits and types.get(identifiant) == attendu
    ]
    return options, libelles


def selecteur_parent(
    conn: sqlite3.Connection, ligne_id: int, cle: str = "parent",
    libelle: str = "Rattacher à",
) -> int | None:
    """Choix du parent d'un nouvel élément, dans une liste unique et indentée.

    La racine reste accessible pour créer une zone, mais n'est jamais le choix
    par défaut : un équipement oublié à la racine disparaît des analyses par
    zone.
    """
    ordre, libelles = options_hierarchiques(conn, ligne_id)
    options: list[int | None] = [None] + list(ordre)
    libelles[None] = "Racine — créer une nouvelle zone"
    defaut = 1 if ordre else 0
    return st.selectbox(
        libelle, options, index=defaut,
        format_func=lambda i: libelles.get(i, str(i)), key=f"{cle}_choix",
        help="Un équipement se rattache à sa zone, un organe à son équipement.",
    )
