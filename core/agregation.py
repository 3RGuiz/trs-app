"""Agrégation par période, par article et par famille (CDC §5.3, §5.2 ter).

Deux règles gouvernent ce module :

- on n'agrège jamais des taux, on agrège des temps : les fonctions retournent des
  sommes de temps, et les indicateurs sont dérivés en dernière étape ;
- le TRS ne se décline PAS par article : Tu se ventile par article, Tr non
  (l'ERP ne donne pas les horaires d'ordre de fabrication). Par article et par
  famille, l'application expose le taux de réalisation, la quantité produite et
  Tu — jamais de TRS, TRG ou TRE.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from core import cadences, historisation, indicateurs
from core.db import iso

PERIODES = ("jour", "semaine", "mois", "annee")


def _cle_periode(dates: pd.Series, periode: str) -> pd.Series:
    """Clé de regroupement temporel. Les semaines suivent le calendrier ISO."""
    horodates = pd.to_datetime(dates)
    if periode == "jour":
        return horodates.dt.strftime("%Y-%m-%d")
    if periode == "semaine":
        iso_cal = horodates.dt.isocalendar()
        return iso_cal["year"].astype(str) + "-S" + iso_cal["week"].astype(str).str.zfill(2)
    if periode == "mois":
        return horodates.dt.strftime("%Y-%m")
    if periode == "annee":
        return horodates.dt.strftime("%Y")
    raise ValueError(f"Période inconnue : {periode}. Choix possibles : {', '.join(PERIODES)}")


def agreger_par_periode(df_cascade: pd.DataFrame, periode: str) -> pd.DataFrame:
    """Agrège une cascade journalière par période : somme des temps PUIS indicateurs.

    Retourne une ligne par période avec les temps sommés et les huit indicateurs.
    Une moyenne de TRS journaliers serait fausse dès que les journées n'ont pas
    la même durée de production.
    """
    if df_cascade.empty:
        return pd.DataFrame()
    df = df_cascade.copy()
    df["periode"] = _cle_periode(df["date"], periode)
    lignes = []
    for cle, groupe in df.groupby("periode", sort=True):
        resultat = indicateurs.indicateurs_periode(groupe)
        resultat.pop("alertes", None)
        lignes.append({"periode": cle, **resultat})
    return pd.DataFrame(lignes)


def _production_resolue(
    conn: sqlite3.Connection, ligne_id: int, date_debut: date | str, date_fin: date | str
) -> pd.DataFrame:
    """Production de la période avec cadence résolue à la date de chaque ligne,
    restreinte à l'historique exploitable et aux jours agrégeables."""
    from core import temps as temps_module

    df = pd.read_sql_query(
        "SELECT date, ligne_id, article_code, qte_planifiee, qte_produite, qte_ensachee"
        " FROM production WHERE ligne_id = ? AND date BETWEEN ? AND ?",
        conn, params=(ligne_id, iso(date_debut), iso(date_fin)),
    )
    if df.empty:
        return df
    df = cadences.resoudre_cadences(conn, df)
    # Exclusion de l'historique non exploitable, ligne à ligne.
    exploitables = []
    for _, ligne in df.iterrows():
        jour = ligne["date"].date() if hasattr(ligne["date"], "date") else ligne["date"]
        debut_historique = temps_module.date_debut_historique(conn, jour)
        exploitables.append(debut_historique is None or jour >= debut_historique)
    return df[pd.Series(exploitables, index=df.index)]


def par_article(
    conn: sqlite3.Connection,
    ligne_id: int,
    date_debut: date | str,
    date_fin: date | str,
) -> pd.DataFrame:
    """Vue par article : taux de réalisation, quantités et temps théorique consommé.

    Ne retourne AUCUN TRS, TRG ou TRE (CDC §5.2 ter) : toute répartition inventée
    de Tr redonnerait le taux de réalisation sous un autre nom.
    """
    df = _production_resolue(conn, ligne_id, date_debut, date_fin)
    colonnes = ["article_code", "qte_planifiee", "qte_produite",
                "temps_theorique_min", "taux_realisation"]
    if df.empty:
        return pd.DataFrame(columns=colonnes)

    df = df.copy()
    df["temps_theorique_min"] = df["qte_produite"] / df["valeur_ppm"]
    groupe = df.groupby("article_code", as_index=False).agg(
        qte_planifiee=("qte_planifiee", "sum"),
        qte_produite=("qte_produite", "sum"),
        temps_theorique_min=("temps_theorique_min", "sum"),
    )
    groupe["taux_realisation"] = groupe.apply(
        lambda ligne: ligne["qte_produite"] / ligne["qte_planifiee"]
        if ligne["qte_planifiee"] else None,
        axis=1,
    )
    return groupe[colonnes]


def par_famille(
    conn: sqlite3.Connection,
    ligne_id: int,
    date_debut: date | str,
    date_fin: date | str,
    vue: str = "historique",
) -> pd.DataFrame:
    """Vue par famille d'articles. Même périmètre que par_article : jamais de TRS.

    vue = 'historique' (défaut) : chaque production est comptée dans la famille en
    vigueur à sa date — le passé ne bouge pas.
    vue = 'actuelle' : tout l'historique est recompté avec le rattachement
    d'aujourd'hui. Le mode choisi doit être affiché à l'écran, jamais implicite.
    """
    if vue not in ("historique", "actuelle"):
        raise ValueError("vue doit valoir 'historique' ou 'actuelle'")

    df = _production_resolue(conn, ligne_id, date_debut, date_fin)
    colonnes = ["famille", "qte_planifiee", "qte_produite",
                "temps_theorique_min", "taux_realisation"]
    if df.empty:
        return pd.DataFrame(columns=colonnes)

    rattachements = pd.read_sql_query(
        "SELECT af.article_code, f.libelle AS famille, af.date_debut, af.date_fin"
        " FROM article_famille af JOIN famille f ON f.id = af.famille_id",
        conn,
    )
    df = df.copy()
    if vue == "actuelle":
        aujourdhui = date.today().isoformat()
        en_vigueur = rattachements[
            (rattachements["date_debut"] <= aujourdhui)
            & (rattachements["date_fin"].isna() | (rattachements["date_fin"] >= aujourdhui))
        ]
        df = df.merge(
            en_vigueur[["article_code", "famille"]], on="article_code", how="left"
        )
    else:
        df = historisation.resoudre_en_masse(rattachements, df, ["article_code"], "date")
    df["famille"] = df["famille"].fillna("Sans famille")

    df["temps_theorique_min"] = df["qte_produite"] / df["valeur_ppm"]
    groupe = df.groupby("famille", as_index=False).agg(
        qte_planifiee=("qte_planifiee", "sum"),
        qte_produite=("qte_produite", "sum"),
        temps_theorique_min=("temps_theorique_min", "sum"),
    )
    groupe["taux_realisation"] = groupe.apply(
        lambda ligne: ligne["qte_produite"] / ligne["qte_planifiee"]
        if ligne["qte_planifiee"] else None,
        axis=1,
    )
    return groupe[colonnes]
