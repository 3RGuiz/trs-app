"""Composant générique de saisie d'un référentiel historisé (CDC §7.3).

Écrit une fois, réutilisé par tous les onglets du référentiel : valeur en vigueur,
frise de l'historique, formulaire de changement avec date d'effet et commentaire
obligatoire. Ne pas dupliquer un formulaire de saisie historisée ailleurs.

Seul l'onglet « Composition de la ligne » fait exception : il a besoin d'une vue
en arbre, et vit dans sa propre page.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import streamlit as st

from core import historisation
from core.erreurs import ErreurMetier
from ui import theme


def frise_historique(
    conn: sqlite3.Connection, table: str, cles: dict, colonnes: dict[str, str]
) -> pd.DataFrame:
    """Toutes les périodes d'une clé, mises en forme pour la lecture.

    colonnes : {nom technique -> libellé affiché}.
    """
    lignes = historisation.historique(conn, table, cles)
    if not lignes:
        return pd.DataFrame()
    affichage = []
    for ligne in lignes:
        entree = {
            "Depuis le": f"{date.fromisoformat(ligne['date_debut']):%d/%m/%Y}",
            "Jusqu'au": (
                f"{date.fromisoformat(ligne['date_fin']):%d/%m/%Y}"
                if ligne["date_fin"] else "en vigueur"
            ),
        }
        for technique, libelle in colonnes.items():
            entree[libelle] = ligne.get(technique)
        affichage.append(entree)
    return pd.DataFrame(affichage)


def formulaire_changement(
    conn: sqlite3.Connection,
    table: str,
    cles: dict,
    champs: dict,
    cle_widget: str,
    avertissement: str | None = None,
    auteur: str = "utilisateur",
) -> bool:
    """Formulaire de changement de valeur avec date d'effet et commentaire.

    champs : {nom de colonne -> dict(libelle=..., type=..., valeur=..., options=...)}
    où type vaut 'nombre', 'entier', 'texte' ou 'choix'.

    Retourne True si un changement a été enregistré. Le commentaire est
    obligatoire : une modification de référentiel sans justification écrite est
    refusée — c'est ce qui permettra de comprendre une rupture de courbe dans
    deux ans.
    """
    with st.form(f"changement_{cle_widget}"):
        saisies = {}
        for colonne, description in champs.items():
            libelle = description.get("libelle", colonne)
            type_champ = description.get("type", "texte")
            valeur = description.get("valeur")
            if type_champ == "nombre":
                saisies[colonne] = st.number_input(
                    libelle, value=float(valeur) if valeur is not None else 0.0,
                    min_value=description.get("minimum", 0.0),
                    step=description.get("pas", 1.0), format="%.2f",
                )
            elif type_champ == "entier":
                saisies[colonne] = st.number_input(
                    libelle, value=int(valeur) if valeur is not None else 0,
                    min_value=int(description.get("minimum", 0)),
                    max_value=int(description.get("maximum", 1440)), step=1,
                )
            elif type_champ == "choix":
                options = description.get("options", [])
                index = options.index(valeur) if valeur in options else 0
                saisies[colonne] = st.selectbox(libelle, options, index=index)
            else:
                saisies[colonne] = st.text_input(libelle, value=valeur or "")

        date_effet = st.date_input(
            "Date de prise d'effet", value=date.today(),
            help="Les périodes antérieures conservent l'ancienne valeur.",
        )
        commentaire = st.text_area(
            "Motif du changement (obligatoire)",
            placeholder="Pourquoi cette valeur change — pas ce qu'elle devient.",
        )
        if avertissement:
            st.info(avertissement)
        valide = st.form_submit_button("Enregistrer le changement")

    if not valide:
        return False
    try:
        historisation.cloturer_et_inserer(
            conn, table, cles, saisies, date_effet, commentaire, auteur
        )
    except ErreurMetier as erreur:
        st.error(str(erreur))
        return False
    st.success(
        f"Changement enregistré, en vigueur à partir du {date_effet:%d/%m/%Y}. "
        "Les périodes antérieures sont inchangées."
    )
    return True


def bloc_referentiel(
    conn: sqlite3.Connection,
    titre: str,
    table: str,
    cles: dict,
    champs: dict,
    colonnes_frise: dict[str, str],
    cle_widget: str,
    rappel: str | None = None,
    avertissement: str | None = None,
) -> bool:
    """Bloc complet : rappel de définition, valeur en vigueur, frise, formulaire."""
    st.subheader(titre)
    if rappel:
        st.caption(rappel)

    en_vigueur = historisation.resoudre(conn, table, cles, date.today())
    if en_vigueur:
        valeurs = " · ".join(
            f"{libelle} : {en_vigueur.get(colonne)}"
            for colonne, libelle in colonnes_frise.items()
        )
        st.markdown(f"**En vigueur aujourd'hui** — {valeurs}")
    else:
        st.warning("Aucune valeur en vigueur à ce jour pour ce référentiel.")

    frise = frise_historique(conn, table, cles, colonnes_frise)
    if not frise.empty:
        with st.expander(f"Historique ({len(frise)} période(s))"):
            st.dataframe(frise, width="stretch", hide_index=True)

    for colonne, description in champs.items():
        if en_vigueur and description.get("valeur") is None:
            description["valeur"] = en_vigueur.get(colonne)

    return formulaire_changement(
        conn, table, cles, champs, cle_widget, avertissement
    )


def journal_modifications(conn: sqlite3.Connection, limite: int = 200) -> pd.DataFrame:
    """Journal en lecture seule : qui a changé quoi, quand, avec quelle raison.

    C'est la page qu'on ouvrira dans deux ans pour comprendre une rupture de courbe.
    """
    df = pd.read_sql_query(
        "SELECT horodatage, table_cible, cle_metier, action, date_effet,"
        " ancienne_valeur, nouvelle_valeur, commentaire, auteur"
        " FROM journal_referentiel ORDER BY id DESC LIMIT ?",
        conn, params=(limite,),
    )
    if df.empty:
        return df
    return df.rename(columns={
        "horodatage": "Saisi le", "table_cible": "Référentiel",
        "cle_metier": "Clé", "action": "Action", "date_effet": "Effet au",
        "ancienne_valeur": "Ancienne valeur", "nouvelle_valeur": "Nouvelle valeur",
        "commentaire": "Motif", "auteur": "Auteur",
    })
