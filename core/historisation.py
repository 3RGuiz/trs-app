"""Socle générique d'historisation des référentiels (CDC §4.0).

Règle unique, appliquée à toutes les tables de référentiel : un changement n'est
jamais un UPDATE de la valeur. C'est la clôture de la ligne en vigueur
(date_fin = veille de la prise d'effet) suivie de l'insertion d'une nouvelle ligne.
Tout calcul résout la valeur à la date de la production concernée, jamais
« la valeur actuelle ».

Tout nouveau référentiel passe par les quatre fonctions de ce module, jamais par
du SQL écrit à la main dans un module métier.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from core.db import iso
from core.erreurs import ChevauchementPeriode, CommentaireObligatoire, ErreurMetier


@dataclass(frozen=True)
class ConfigTable:
    """Décrit une table historisée : ses colonnes clés et ses colonnes de valeur."""

    cles: tuple[str, ...]
    valeurs: tuple[str, ...]


# Tables passant par le socle générique. element_ligne est historisée aussi, mais
# gérée par core/elements.py (arborescence, chemin matérialisé, remplacement).
TABLES_HISTORISEES: dict[str, ConfigTable] = {
    "cadence": ConfigTable(cles=("article_code", "ligne_id"), valeurs=("valeur_ppm",)),
    "calendrier_type": ConfigTable(cles=("ligne_id", "jour_semaine"), valeurs=("to_min", "tr_min")),
    "motif_classement": ConfigTable(cles=("motif_id",), valeurs=("categorie", "famille")),
    "motif_element": ConfigTable(cles=("motif_id", "element_id"), valeurs=()),
    "article_famille": ConfigTable(cles=("article_code",), valeurs=("famille_id",)),
    "article_format": ConfigTable(cles=("article_code",), valeurs=("libelle_format", "poids_unitaire_g")),
    "objectif": ConfigTable(cles=("perimetre", "perimetre_ref", "indicateur"), valeurs=("cible", "seuil_alerte")),
    "parametre_date": ConfigTable(cles=("cle",), valeurs=("valeur",)),
}


def _config(table: str) -> ConfigTable:
    try:
        return TABLES_HISTORISEES[table]
    except KeyError:
        raise ErreurMetier(
            f"La table « {table} » n'est pas déclarée comme référentiel historisé. "
            "Ajoutez-la à TABLES_HISTORISEES dans core/historisation.py."
        ) from None


def _clause_cles(cles: dict) -> tuple[str, list]:
    """Construit la clause WHERE d'égalité sur les clés, en gérant les clés NULL."""
    morceaux, parametres = [], []
    for colonne, valeur in cles.items():
        if valeur is None:
            morceaux.append(f"{colonne} IS NULL")
        else:
            morceaux.append(f"{colonne} = ?")
            parametres.append(valeur)
    return " AND ".join(morceaux), parametres


def cle_metier(cles: dict) -> str:
    """Représentation lisible de la clé, pour le journal (ex. « ART-001 / 1 »)."""
    return " / ".join("∅" if v is None else str(v) for v in cles.values())


def valider_non_chevauchement(
    conn: sqlite3.Connection,
    table: str,
    cles: dict,
    date_debut: date | str,
    date_fin: date | str | None,
    ignorer_id: int | None = None,
) -> None:
    """Lève une erreur explicite si la nouvelle période chevauche une période existante."""
    _config(table)  # vérifie que la table est bien déclarée
    ou, parametres = _clause_cles(cles)
    debut = iso(date_debut)
    fin = iso(date_fin) if date_fin is not None else None
    requete = (
        f"SELECT * FROM {table} WHERE {ou}"
        " AND (? IS NULL OR date_debut <= ?)"          # l'existante commence avant la fin de la nouvelle
        " AND (date_fin IS NULL OR date_fin >= ?)"     # et finit après le début de la nouvelle
    )
    if ignorer_id is not None:
        requete += " AND id != ?"
        parametres = parametres + [fin, fin, debut, ignorer_id]
    else:
        parametres = parametres + [fin, fin, debut]
    conflit = conn.execute(requete, parametres).fetchone()
    if conflit:
        fin_conflit = conflit["date_fin"] or "en cours"
        raise ChevauchementPeriode(
            f"Impossible d'enregistrer la période du {debut} au {fin or 'en cours'} : "
            f"elle chevauche la période existante du {conflit['date_debut']} au {fin_conflit} "
            f"({table}, clé {cle_metier(cles)}). Clôturez d'abord la période en vigueur, "
            "ou choisissez une autre date d'effet."
        )


def cloturer_et_inserer(
    conn: sqlite3.Connection,
    table: str,
    cles: dict,
    valeurs: dict,
    date_effet: date | str,
    commentaire: str,
    auteur: str,
) -> int:
    """Clôture la ligne en vigueur (date_fin = date_effet - 1 jour) et insère la nouvelle.

    Écrit systématiquement une entrée — exactement une — dans journal_referentiel.
    Transactionnel : tout passe ou rien ne passe.
    """
    config = _config(table)
    if not commentaire or not commentaire.strip():
        raise CommentaireObligatoire(
            "Une modification de référentiel doit être justifiée par un commentaire : "
            "c'est ce qui permettra de comprendre, dans deux ans, pourquoi un indicateur a bougé."
        )
    if not auteur or not str(auteur).strip():
        raise ErreurMetier("L'auteur de la modification doit être renseigné.")
    inconnues = set(valeurs) - set(config.valeurs)
    if inconnues:
        raise ErreurMetier(
            f"Colonnes inconnues pour {table} : {', '.join(sorted(inconnues))}."
        )

    effet = date.fromisoformat(iso(date_effet))
    ou, parametres = _clause_cles(cles)

    try:
        # Ligne en vigueur à la date d'effet (ou ouverte avant elle).
        courante = conn.execute(
            f"SELECT * FROM {table} WHERE {ou} AND date_debut <= ?"
            " AND (date_fin IS NULL OR date_fin >= ?)",
            parametres + [effet.isoformat(), effet.isoformat()],
        ).fetchone()

        ancienne_valeur = None
        action = "CREATION"
        if courante is not None:
            if courante["date_debut"] == effet.isoformat():
                raise ChevauchementPeriode(
                    f"Une valeur de {table} (clé {cle_metier(cles)}) prend déjà effet "
                    f"au {effet.isoformat()}. Choisissez une autre date d'effet, ou corrigez "
                    "la valeur existante depuis le référentiel."
                )
            veille = (effet - timedelta(days=1)).isoformat()
            conn.execute(
                f"UPDATE {table} SET date_fin = ? WHERE id = ?",
                (veille, courante["id"]),
            )
            ancienne_valeur = json.dumps(
                {c: courante[c] for c in config.valeurs}, ensure_ascii=False
            )
            action = "CLOTURE"

        valider_non_chevauchement(conn, table, cles, effet, None)

        colonnes = list(cles) + list(valeurs) + ["date_debut"]
        contenus = list(cles.values()) + list(valeurs.values()) + [effet.isoformat()]
        marques = ", ".join("?" for _ in colonnes)
        cur = conn.execute(
            f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES ({marques})",
            contenus,
        )
        nouvel_id = cur.lastrowid

        conn.execute(
            "INSERT INTO journal_referentiel"
            " (table_cible, cle_metier, action, ancienne_valeur, nouvelle_valeur,"
            "  date_effet, commentaire, auteur)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                table,
                cle_metier(cles),
                action,
                ancienne_valeur,
                json.dumps(valeurs, ensure_ascii=False),
                effet.isoformat(),
                commentaire.strip(),
                str(auteur).strip(),
            ),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return nouvel_id


def resoudre(conn: sqlite3.Connection, table: str, cles: dict, d: date | str) -> dict | None:
    """Retourne la ligne en vigueur à la date d, ou None."""
    _config(table)
    ou, parametres = _clause_cles(cles)
    jour = iso(d)
    ligne = conn.execute(
        f"SELECT * FROM {table} WHERE {ou} AND date_debut <= ?"
        " AND (date_fin IS NULL OR date_fin >= ?)",
        parametres + [jour, jour],
    ).fetchone()
    return dict(ligne) if ligne is not None else None


def resoudre_en_masse(
    referentiel: pd.DataFrame,
    df: pd.DataFrame,
    col_cles: list[str],
    col_date: str,
) -> pd.DataFrame:
    """Version vectorisée de resoudre() (merge_asof), pour les calculs sur volume.

    referentiel : contenu de la table historisée (avec date_debut / date_fin).
    df          : données à résoudre, portant les colonnes de clés et une colonne date.
    Retourne df enrichi des colonnes de valeur du référentiel ; NaN quand aucune
    période ne couvre la date — c'est à l'appelant de rejeter ces lignes, jamais
    de leur appliquer une valeur par défaut.
    """
    if df.empty:
        return df.copy()

    resultat = df.copy()
    resultat[col_date] = pd.to_datetime(resultat[col_date])
    colonnes_valeur = [
        c for c in referentiel.columns
        if c not in ("id", "date_debut", "date_fin", *col_cles)
    ]

    if referentiel.empty:
        for colonne in colonnes_valeur:
            resultat[colonne] = pd.NA
        return resultat

    # Les bornes du référentiel sont renommées : elles ne doivent pas entrer en
    # collision avec les colonnes du DataFrame appelant (résolutions en chaîne).
    ref = referentiel.rename(
        columns={"date_debut": "__periode_debut", "date_fin": "__periode_fin"}
    ).copy()
    ref["__periode_debut"] = pd.to_datetime(ref["__periode_debut"])
    ref["__periode_fin"] = pd.to_datetime(ref["__periode_fin"])
    ref = ref.sort_values("__periode_debut")

    ordre_initial = resultat.index
    resultat = resultat.sort_values(col_date)
    fusion = pd.merge_asof(
        resultat,
        ref[[*col_cles, "__periode_debut", "__periode_fin", *colonnes_valeur]],
        left_on=col_date,
        right_on="__periode_debut",
        by=col_cles if col_cles else None,
        direction="backward",
    )
    fusion.index = resultat.index

    # Une période close avant la date ne s'applique pas : on invalide la résolution.
    perimee = fusion["__periode_fin"].notna() & (fusion["__periode_fin"] < fusion[col_date])
    for colonne in colonnes_valeur:
        fusion.loc[perimee, colonne] = pd.NA

    fusion = fusion.drop(columns=["__periode_debut", "__periode_fin"])
    return fusion.loc[ordre_initial]


def historique(conn: sqlite3.Connection, table: str, cles: dict) -> list[dict]:
    """Toutes les périodes d'une clé, de la plus ancienne à la plus récente (frise)."""
    _config(table)
    ou, parametres = _clause_cles(cles)
    lignes = conn.execute(
        f"SELECT * FROM {table} WHERE {ou} ORDER BY date_debut", parametres
    ).fetchall()
    return [dict(ligne) for ligne in lignes]
