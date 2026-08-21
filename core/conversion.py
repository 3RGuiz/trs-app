"""Conversion des valeurs issues des fichiers ERP (CDC §7 bis.1).

Les exports Windows français arrivent avec virgule décimale, espaces insécables
en séparateur de milliers et dates jj/mm/aaaa. La règle : lire en texte, puis
convertir explicitement — et LEVER UNE ERREUR quand une valeur résiste, jamais
de coercition silencieuse vers NaN. Une colonne quantité restée en texte fait
concaténer .sum() au lieu d'additionner, sans lever d'erreur : c'est l'erreur
silencieuse la plus dangereuse du projet.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from core.erreurs import ValeurNonConvertible

# Espaces à retirer des nombres : normale, insécable, fine insécable, fine.
_ESPACES = str.maketrans("", "", " \xa0\u202f\u2009")

FORMATS_DATE = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y")


def convertir_nombre(valeur, colonne: str = "") -> float | None:
    """Convertit une valeur de fichier ERP en nombre. None pour une cellule vide.

    Retire les espaces (y compris insécables), remplace la virgule par un point,
    et lève ValeurNonConvertible si la valeur résiste — jamais de NaN silencieux.
    """
    if valeur is None:
        return None
    if isinstance(valeur, (int, float)):
        return None if pd.isna(valeur) else float(valeur)
    texte = str(valeur).translate(_ESPACES).replace(",", ".").strip()
    if texte == "" or texte.lower() in ("nan", "none"):
        return None
    try:
        return float(texte)
    except ValueError:
        raise ValeurNonConvertible(
            f"La valeur « {valeur} »"
            + (f" de la colonne « {colonne} »" if colonne else "")
            + " n'est pas un nombre. Corrigez le fichier avant de réimporter — "
            "l'import s'arrête plutôt que de produire un total faux."
        ) from None


def convertir_date(valeur, colonne: str = "", format_prefere: str | None = None) -> date | None:
    """Convertit une date de fichier ERP, avec un format explicite — jamais par inférence."""
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    if texte == "" or texte.lower() in ("nan", "none", "nat"):
        return None
    if " " in texte:                       # horodatage : ne garder que la date
        texte = texte.split(" ")[0]
    formats = [format_prefere] if format_prefere else []
    formats += [f for f in FORMATS_DATE if f not in formats]
    for format_essaye in formats:
        try:
            return datetime.strptime(texte, format_essaye).date()
        except (ValueError, TypeError):
            continue
    raise ValeurNonConvertible(
        f"La valeur « {valeur} »"
        + (f" de la colonne « {colonne} »" if colonne else "")
        + " n'est pas une date reconnue (formats acceptés : jj/mm/aaaa, aaaa-mm-jj)."
    )


def convertir_colonne_nombre(serie: pd.Series, colonne: str) -> pd.Series:
    """Convertit une colonne entière et ASSERTE le type numérique du résultat.

    C'est l'assertion qui attrape tout le reste : sans elle, une colonne restée
    en texte se concatène au lieu de s'additionner.
    """
    convertie = serie.map(lambda v: convertir_nombre(v, colonne)).astype("float64")
    if not pd.api.types.is_numeric_dtype(convertie):
        raise ValeurNonConvertible(
            f"La colonne « {colonne} » n'est pas numérique après conversion. "
            "Vérifiez le fichier importé."
        )
    return convertie


def convertir_colonne_date(serie: pd.Series, colonne: str,
                           format_prefere: str | None = None) -> pd.Series:
    return serie.map(lambda v: convertir_date(v, colonne, format_prefere))
