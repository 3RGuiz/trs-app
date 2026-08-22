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

import streamlit as st

MAILLES = ("jour", "semaine", "mois", "annee")

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
        # Changer de maille recale la profondeur : sans cela, passer en « mois »
        # sur trente jours donne une courbe à un seul point.
        st.session_state._periode_maille = choix
        st.session_state._periode_fin = fin_connue
        st.session_state._periode_debut = fin_connue - PROFONDEUR_PAR_MAILLE[choix]
        st.session_state._periode_version += 1

    with st.container(border=True):
        haut = st.columns([3, 2]) if avec_maille else [st.container()]

        with haut[0]:
            st.caption("Période")
            st.segmented_control(
                "Période", list(RACCOURCIS), key=f"{cle}_raccourci",
                on_change=_appliquer_raccourci, label_visibility="collapsed",
            )

        if avec_maille:
            with haut[1]:
                st.caption("Maille d'analyse")
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
        debut = dates[0].date_input(
            "Du", value=st.session_state._periode_debut,
            key=f"{cle}_debut_{version}", format="DD/MM/YYYY",
        )
        fin = dates[1].date_input(
            "Au", value=st.session_state._periode_fin,
            key=f"{cle}_fin_{version}", format="DD/MM/YYYY",
        )
        st.session_state._periode_debut = debut
        st.session_state._periode_fin = fin

        with dates[2]:
            st.caption("")     # aligne le texte sur la ligne des champs
            if debut and fin and fin < debut:
                st.error("La fin de période précède son début.")
            elif debut and fin:
                jours = (fin - debut).days + 1
                maille_lue = LIBELLES_MAILLE[st.session_state._periode_maille].lower()
                st.caption(
                    f"{jours} jour(s) analysé(s)"
                    + (f", regroupés par {maille_lue}" if avec_maille else "")
                )

    return Periode(debut, fin, st.session_state._periode_maille)
