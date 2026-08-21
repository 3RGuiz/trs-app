"""Éléments partagés par toutes les pages : connexion, erreurs, fraîcheur.

Streamlit est configuré avec showErrorDetails = "none" : rien ne s'affiche de
lui-même en cas d'erreur. Chaque page doit donc rattraper ses erreurs et les
expliquer en français. Le détail technique part en console, jamais à l'écran.
"""

from __future__ import annotations

import logging
import sqlite3
import tomllib
from datetime import date
from pathlib import Path

import streamlit as st

from core import db
from core.erreurs import ErreurMetier

RACINE = Path(__file__).parent.parent
journal = logging.getLogger("trs")


def signaler(message: str, erreur: Exception | None = None) -> None:
    """Affiche une erreur compréhensible et interrompt la page proprement.

    Ne jamais appeler depuis l'intérieur d'un bloc try surveillé par un except
    large : st.stop() lève une exception interne à Streamlit.
    """
    if erreur is not None:
        journal.exception(message)
    st.error(message)
    st.stop()


def chemin_base() -> Path:
    """Chemin de la base, lu dans config.toml — jamais écrit en dur."""
    config = RACINE / "config.toml"
    if config.exists():
        contenu = tomllib.loads(config.read_text(encoding="utf-8"))
        return RACINE / contenu.get("base", {}).get("chemin", "data/trs.db")
    return RACINE / "data" / "trs.db"


def ouvrir() -> sqlite3.Connection:
    """Ouvre la base en expliquant l'échec en français plutôt qu'en stack trace."""
    try:
        return db.ouvrir_base(chemin_base())
    except tomllib.TOMLDecodeError as erreur:
        signaler(
            "Le fichier de configuration config.toml est illisible. Corrigez-le "
            "ou supprimez-le pour revenir aux valeurs par défaut.", erreur,
        )
    except ErreurMetier as erreur:
        signaler(str(erreur), erreur)
    except Exception as erreur:
        signaler(
            f"Impossible d'ouvrir la base de données ({chemin_base()}). Vérifiez "
            "que le fichier existe, qu'il n'est pas ouvert par un autre programme, "
            "et que le dossier est accessible.", erreur,
        )


def ligne_active(conn: sqlite3.Connection) -> dict | None:
    """Première ligne en service, ou None si le référentiel est vide."""
    ligne = conn.execute(
        "SELECT * FROM ligne WHERE date_fin IS NULL ORDER BY code LIMIT 1"
    ).fetchone()
    return dict(ligne) if ligne else None


def exiger_ligne(conn: sqlite3.Connection) -> dict:
    """Récupère la ligne à analyser, ou explique comment démarrer."""
    ligne = ligne_active(conn)
    if ligne is None:
        st.info(
            "Aucune ligne de production n'est encore déclarée. Créez-la depuis la "
            "page Référentiel, avec ses cadences et son calendrier. Pour essayer "
            "l'application sans données réelles : `python generer_donnees_test.py`."
        )
        st.stop()
    return ligne


def bandeau_fraicheur(conn: sqlite3.Connection, ligne_id: int) -> str | None:
    """Affiche la date des données et alerte au-delà de 7 jours (CDC §6.7).

    Retourne la date de production la plus récente, ou None s'il n'y en a aucune.
    """
    derniere = conn.execute(
        "SELECT MAX(date) FROM production WHERE ligne_id = ?", (ligne_id,)
    ).fetchone()[0]
    dernier_import = conn.execute("SELECT MAX(date_import) FROM import_log").fetchone()[0]
    if derniere is None:
        st.warning(
            "Aucune donnée de production importée. Rendez-vous sur la page Import."
        )
        return None
    st.caption(
        f"Données à jour au {date.fromisoformat(derniere):%d/%m/%Y}"
        + (f" — dernier import le {dernier_import}" if dernier_import else "")
    )
    retard = (date.today() - date.fromisoformat(derniere)).days
    if retard > 7:
        st.warning(
            f"Les données datent de {retard} jours. Une extraction plus récente "
            "est peut-être disponible."
        )
    return derniere


def valider_periode(debut, fin) -> None:
    """Refuse une période impossible avant tout calcul."""
    if debut is None or fin is None:
        signaler("Renseignez une date de début et une date de fin.")
    if fin < debut:
        signaler(
            f"La fin de période ({fin:%d/%m/%Y}) est antérieure à son début "
            f"({debut:%d/%m/%Y}). Inversez les deux dates."
        )


def mention_niveau(resultat: dict) -> None:
    """Rappelle en permanence ce qui est mesuré et ce qui ne l'est pas (CDC §5.0)."""
    niveaux = {
        1: "Niveau 1 — TRS, TRG et TRE exacts. DO, TP et TQ non décomposés : "
           "aucun arrêt saisi, pas de compteur d'ensacheuse.",
        2: "Niveau 2 — arrêts saisis : DO et TP mesurés. TQ non mesuré : "
           "l'écart de cadence et la non-qualité restent regroupés.",
        3: "Niveau 3 — arrêts saisis et compteur d'ensacheuse : "
           "la cascade est entièrement décomposée.",
    }
    st.caption(niveaux[resultat["niveau_donnees"]])
