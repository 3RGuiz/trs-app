"""Sélecteur de période partagé par les écrans d'analyse.

Trois choses qu'un tableau de bord doit faire et qu'une paire de champs de date
ne fait pas :

- **la maille commande la profondeur.** Passer en mois avec trente jours à
  l'écran donne un graphique à un point. Changer de maille recale donc la
  période sur une profondeur qui a du sens, tout en laissant l'ajuster ensuite.
- **des raccourcis plutôt que deux calendriers.** « Ce mois-ci », « 12 mois »
  couvrent la quasi-totalité des usages sans saisir une seule date.
- **le choix suit d'un écran à l'autre.** Régler la période sur le tableau de
  bord puis la ressaisir sur l'écran TRS n'a aucun intérêt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import agregation

MAILLES = ("jour", "semaine", "mois", "annee")

# En dessous de trois points, une courbe ne raconte rien : la période est alors
# élargie d'office. Au-delà de soixante, elle devient illisible et on le signale,
# sans rien imposer — réduire une période choisie serait pire que le défaut.
MINIMUM_POINTS = 3
MAXIMUM_LISIBLE = 60

LIBELLES_MAILLE = {
    "jour": "Jour", "semaine": "Semaine", "mois": "Mois", "annee": "Année",
}

# Profondeur par défaut de chaque maille : de quoi tracer une courbe lisible.
PROFONDEUR_PAR_MAILLE = {
    "jour": timedelta(days=29),
    "semaine": timedelta(weeks=12),
    "mois": timedelta(days=365),
    "annee": timedelta(days=365 * 3),
}

RACCOURCIS = {
    "7 jours": lambda fin: (fin - timedelta(days=6), fin),
    "30 jours": lambda fin: (fin - timedelta(days=29), fin),
    "Ce mois-ci": lambda fin: (fin.replace(day=1), fin),
    "3 mois": lambda fin: (fin - timedelta(days=90), fin),
    "12 mois": lambda fin: (fin - timedelta(days=364), fin),
}


@dataclass(frozen=True)
class Periode:
    debut: date
    fin: date
    maille: str

    @property
    def libelle(self) -> str:
        return f"du {self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y}"

    @property
    def nb_jours(self) -> int:
        return (self.fin - self.debut).days + 1


def nb_points(debut: date, fin: date, maille: str) -> int:
    """Nombre de points que donnera le graphique : c'est le produit des deux
    réglages, et donc ce qu'il faut montrer à l'utilisateur."""
    if not debut or not fin or fin < debut:
        return 0
    jours = pd.Series(pd.date_range(debut, fin, freq="D"))
    return int(agregation.cle_periode(jours, maille).nunique())


def _accord(nombre: int, maille: str) -> str:
    """« 4 semaines », « 1 mois » — le résultat du couple période × maille."""
    singulier = {"jour": "jour", "semaine": "semaine", "mois": "mois", "annee": "année"}
    mot = singulier[maille]
    if nombre > 1 and mot != "mois":
        mot += "s"
    return f"{nombre} {mot}"


def _borne_haute(conn: sqlite3.Connection, ligne_id: int) -> date:
    """Dernier jour de production connu : analyser au-delà n'apporte rien."""
    derniere = conn.execute(
        "SELECT MAX(date) FROM production WHERE ligne_id = ?", (ligne_id,)
    ).fetchone()[0]
    return date.fromisoformat(derniere) if derniere else date.today()


def selecteur(
    conn: sqlite3.Connection,
    ligne_id: int,
    cle: str = "periode",
    avec_maille: bool = True,
) -> Periode:
    """Barre de période : raccourcis, maille, et dates ajustables.

    L'état est partagé entre les écrans par st.session_state : la période
    choisie ici vaut pour toutes les pages d'analyse.
    """
    fin_connue = _borne_haute(conn, ligne_id)

    if "_periode_debut" not in st.session_state:
        st.session_state._periode_maille = "semaine"
        st.session_state._periode_fin = fin_connue
        st.session_state._periode_debut = fin_connue - PROFONDEUR_PAR_MAILLE["semaine"]
        # Les champs de date sont recréés à chaque recalage automatique : sans
        # cela, ils garderaient la valeur saisie par l'utilisateur.
        st.session_state._periode_version = 0

    def _appliquer_raccourci() -> None:
        choix = st.session_state.get(f"{cle}_raccourci")
        if not choix:
            return
        debut, fin = RACCOURCIS[choix](fin_connue)
        st.session_state._periode_debut = debut
        st.session_state._periode_fin = fin
        st.session_state._periode_version += 1

    def _appliquer_maille() -> None:
        choix = st.session_state.get(f"{cle}_maille")
        if not choix or choix == st.session_state._periode_maille:
            return
        st.session_state._periode_maille = choix
        st.session_state._periode_elargie = None

        # La maille ne redéfinit pas ce qu'on regarde : elle dit comment le
        # regrouper. On n'élargit donc que si la période choisie est trop courte
        # pour tracer quoi que ce soit — sinon, on respecte le choix fait.
        points = nb_points(
            st.session_state._periode_debut, st.session_state._periode_fin, choix
        )
        if points >= MINIMUM_POINTS:
            return
        st.session_state._periode_fin = fin_connue
        st.session_state._periode_debut = fin_connue - PROFONDEUR_PAR_MAILLE[choix]
        st.session_state._periode_elargie = choix
        st.session_state._periode_version += 1

    with st.container(border=True):
        haut = st.columns([3, 2]) if avec_maille else [st.container()]

        with haut[0]:
            st.caption("Période analysée")
            st.segmented_control(
                "Période", list(RACCOURCIS), key=f"{cle}_raccourci",
                on_change=_appliquer_raccourci, label_visibility="collapsed",
            )

        if avec_maille:
            with haut[1]:
                st.caption("Regrouper par")
                if f"{cle}_maille" not in st.session_state:
                    st.session_state[f"{cle}_maille"] = st.session_state._periode_maille
                st.segmented_control(
                    "Maille", MAILLES, key=f"{cle}_maille",
                    on_change=_appliquer_maille,
                    format_func=lambda m: LIBELLES_MAILLE[m],
                    label_visibility="collapsed",
                )

        version = st.session_state._periode_version
        dates = st.columns([1, 1, 2])
        # « Du » reste libre : le borner par « Au » empêcherait de déplacer la
        # période vers le futur sans changer les deux champs dans le bon ordre.
        debut = dates[0].date_input(
            "Du", value=st.session_state._periode_debut,
            key=f"{cle}_debut_{version}", format="DD/MM/YYYY",
            help="Premier jour pris en compte.",
        )
        # « Au » ne peut pas précéder « Du » : le calendrier grise les dates
        # impossibles, plutôt que de laisser saisir une période à l'envers puis
        # de la refuser. Si le début vient de dépasser la fin, celle-ci suit.
        # L'enregistrement précède le rerun, sans quoi la date tout juste
        # saisie serait perdue au rendu suivant.
        if debut:
            st.session_state._periode_debut = debut
        if debut and st.session_state._periode_fin < debut:
            st.session_state._periode_fin = debut
            st.session_state._periode_version += 1
            st.rerun()
        fin = dates[1].date_input(
            "Au", value=st.session_state._periode_fin,
            min_value=debut or st.session_state._periode_debut,
            key=f"{cle}_fin_{version}", format="DD/MM/YYYY",
            help="Dernier jour pris en compte. Ne peut pas précéder la date de début.",
        )
        st.session_state._periode_debut = debut
        st.session_state._periode_fin = fin

        maille_courante = st.session_state._periode_maille
        with dates[2]:
            st.caption("")     # aligne le texte sur la ligne des champs
            if debut and fin and fin < debut:
                st.error("La fin de période précède son début.")
            elif debut and fin:
                jours = (fin - debut).days + 1
                if avec_maille:
                    points = nb_points(debut, fin, maille_courante)
                    # Dire ce que produit la combinaison des deux réglages :
                    # c'est la seule façon de rendre leur interaction évidente.
                    st.caption(
                        f"{jours} jour(s) analysé(s), regroupés en "
                        f"**{_accord(points, maille_courante)}**"
                    )
                else:
                    st.caption(f"{jours} jour(s) analysé(s)")

        if avec_maille and debut and fin and fin >= debut:
            points = nb_points(debut, fin, maille_courante)
            elargie = st.session_state.get("_periode_elargie")
            if elargie == maille_courante:
                st.caption(
                    f"Période élargie automatiquement : elle était trop courte "
                    f"pour une lecture par {LIBELLES_MAILLE[elargie].lower()}. "
                    "Ajustez les dates ci-dessus si besoin."
                )
            elif points > MAXIMUM_LISIBLE:
                st.caption(
                    f"{points} points sur le graphique : la courbe sera dense. "
                    "Un regroupement plus large la rendrait plus lisible."
                )

    return Periode(debut, fin, st.session_state._periode_maille)
