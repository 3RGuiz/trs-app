"""Cadences de référence historisées (CDC §4.2) — table centrale du projet.

La cadence de référence est la capacité de la LIGNE COMPLÈTE, goulot inclus.
Elle n'est jamais modifiée en place ni ajustée après coup : un changement clôture
la période en vigueur et en insère une nouvelle, via core/historisation.py.

Aucun trou n'est toléré silencieusement : une production sans cadence applicable
est exclue des calculs et signalée, jamais calculée avec une valeur par défaut.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from core import historisation
from core.db import iso


def cadence_applicable(
    conn: sqlite3.Connection, article_code: str, ligne_id: int, d: date | str
) -> dict | None:
    """Retourne la cadence en vigueur pour cet article à la date d, ou None."""
    return historisation.resoudre(
        conn, "cadence", {"article_code": article_code, "ligne_id": ligne_id}, d
    )


def changer_cadence(
    conn: sqlite3.Connection,
    article_code: str,
    ligne_id: int,
    valeur_ppm: float,
    date_effet: date | str,
    commentaire: str,
    auteur: str,
) -> int:
    """Clôture la cadence en vigueur et insère la nouvelle, avec trace au journal.

    Les périodes antérieures conservent l'ancienne cadence : le passé ne change jamais.
    """
    from core.erreurs import ErreurMetier

    if valeur_ppm is None or float(valeur_ppm) <= 0:
        raise ErreurMetier("La cadence doit être un nombre de paquets par minute supérieur à zéro.")
    return historisation.cloturer_et_inserer(
        conn, "cadence",
        {"article_code": article_code, "ligne_id": ligne_id},
        {"valeur_ppm": float(valeur_ppm)},
        date_effet, commentaire, auteur,
    )


def resoudre_cadences(
    conn: sqlite3.Connection, df_production: pd.DataFrame
) -> pd.DataFrame:
    """Résout en masse la cadence applicable à chaque ligne de production (merge_asof).

    Ajoute la colonne valeur_ppm ; NaN quand aucune cadence ne couvre la date —
    ces lignes sont à exclure des calculs et à signaler, jamais à compléter
    par une valeur par défaut.
    """
    referentiel = pd.read_sql_query(
        "SELECT article_code, ligne_id, valeur_ppm, date_debut, date_fin FROM cadence",
        conn,
    )
    return historisation.resoudre_en_masse(
        referentiel, df_production, ["article_code", "ligne_id"], "date"
    )


def dates_changement(
    conn: sqlite3.Connection, ligne_id: int,
    date_debut: date | str | None = None, date_fin: date | str | None = None,
) -> list[str]:
    """Dates de prise d'effet d'un changement de cadence sur la période.

    Sert aux repères verticaux des courbes et au bandeau d'avertissement de
    comparabilité (CDC §4.2) : comparer deux périodes de part et d'autre d'un
    changement de référence est trompeur sans le signaler.
    """
    requete = (
        "SELECT DISTINCT date_debut FROM cadence WHERE ligne_id = ?"
        " AND date_debut > (SELECT MIN(date_debut) FROM cadence WHERE ligne_id = ?)"
    )
    parametres: list = [ligne_id, ligne_id]
    if date_debut is not None:
        requete += " AND date_debut >= ?"
        parametres.append(iso(date_debut))
    if date_fin is not None:
        requete += " AND date_debut <= ?"
        parametres.append(iso(date_fin))
    return [ligne[0] for ligne in conn.execute(requete + " ORDER BY date_debut", parametres)]
