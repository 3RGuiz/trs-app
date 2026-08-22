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


def selecteur_element(
    conn: sqlite3.Connection,
    ligne_id: int,
    jour: date | str | None = None,
    cle: str = "element",
    libelle: str = "Élément",
    autoriser_aucun: bool = True,
    autoriser_zone: bool = True,
) -> int | None:
    """Choix d'un élément en deux temps : la zone, puis l'équipement.

    Sur une ligne de quarante équipements, une liste unique impose de tout
    parcourir. En deux étapes, on lit huit zones puis quatre ou cinq machines.
    """
    zones, contenu, hors_zone = grouper_par_zone(conn, ligne_id, jour)
    if not zones and not hors_zone:
        st.caption("Aucun élément en service à cette date.")
        return None

    colonnes = st.columns(2)
    options_zones: list[int | None] = [z["id"] for z in zones]
    if hors_zone:
        options_zones.append(-1)          # groupe des éléments non rattachés
    if autoriser_aucun:
        options_zones.insert(0, None)

    def _nom_zone(identifiant):
        if identifiant is None:
            return "Origine non renseignée"
        if identifiant == -1:
            return f"Hors zone ({len(hors_zone)})"
        zone = next(z for z in zones if z["id"] == identifiant)
        return f"{zone['libelle']} ({len(contenu.get(identifiant, []))})"

    zone_choisie = colonnes[0].selectbox(
        f"{libelle} — zone", options_zones, format_func=_nom_zone, key=f"{cle}_zone",
    )
    if zone_choisie is None:
        return None

    candidats = hors_zone if zone_choisie == -1 else contenu.get(zone_choisie, [])
    options: list[int | None] = [e["id"] for e in candidats]
    if autoriser_zone and zone_choisie != -1:
        # Rattacher à la zone elle-même reste possible : tous les arrêts ne se
        # rapportent pas à une machine précise.
        options.insert(0, zone_choisie)
    if not options:
        colonnes[1].caption("Cette zone ne contient aucun équipement.")
        return zone_choisie if autoriser_zone and zone_choisie != -1 else None

    noms = {e["id"]: e["libelle"] for e in candidats}
    if autoriser_zone and zone_choisie != -1:
        noms[zone_choisie] = f"{_nom_zone(zone_choisie).split(' (')[0]} (la zone entière)"

    return colonnes[1].selectbox(
        f"{libelle} — équipement", options,
        format_func=lambda i: noms.get(i, str(i)), key=f"{cle}_equipement",
    )


def selecteur_parent(
    conn: sqlite3.Connection, ligne_id: int, cle: str = "parent",
    libelle: str = "Rattacher à",
) -> int | None:
    """Choix du parent d'un nouvel élément : racine, une zone, ou un équipement.

    La racine reste accessible pour créer une zone, mais elle n'est jamais le
    choix par défaut : un équipement oublié à la racine disparaît des analyses
    par zone.
    """
    zones, contenu, _ = grouper_par_zone(conn, ligne_id)
    options: list[int | None] = [None] + [z["id"] for z in zones]
    noms = {z["id"]: z["libelle"] for z in zones}

    colonnes = st.columns(2)
    parent = colonnes[0].selectbox(
        libelle, options,
        format_func=lambda i: "Racine — créer une nouvelle zone" if i is None
        else f"Zone {noms[i]}",
        index=1 if zones else 0, key=f"{cle}_zone",
    )
    if parent is None:
        return None

    enfants = contenu.get(parent, [])
    if not enfants:
        return parent
    sous_options: list[int | None] = [parent] + [e["id"] for e in enfants]
    sous_noms = {e["id"]: e["libelle"] for e in enfants}
    sous_noms[parent] = f"Directement dans {noms[parent]}"
    return colonnes[1].selectbox(
        "Niveau", sous_options, format_func=lambda i: sous_noms[i],
        key=f"{cle}_sous_niveau",
        help="Un organe se rattache à son équipement, un équipement à sa zone.",
    )
