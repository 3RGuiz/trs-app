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


def cle_periode(dates: pd.Series, periode: str) -> pd.Series:
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
    df["periode"] = cle_periode(df["date"], periode)
    lignes = []
    for cle, groupe in df.groupby("periode", sort=True):
        resultat = indicateurs.indicateurs_periode(groupe)
        resultat.pop("alertes", None)
        lignes.append({"periode": cle, **resultat})
    return pd.DataFrame(lignes)


def comparer_periodes(
    conn: sqlite3.Connection,
    ligne_id: int,
    periode_a: tuple[date | str, date | str],
    periode_b: tuple[date | str, date | str],
    cadence_constante: float | None = None,
) -> dict:
    """Compare deux périodes, avec un mode « à cadence constante » (CDC §4.2).

    Quand la cadence de référence change entre les deux périodes, le TRS chute
    mécaniquement sans qu'aucune performance réelle n'ait baissé : la barre a
    monté. Le passé reste juste, mais la comparaison devient trompeuse.

    Cette fonction retourne donc toujours les deux lectures :
    - `reelle` — chaque période avec la cadence en vigueur à ses dates ;
    - `constante` — les deux périodes recalculées avec la même cadence, ce qui
      isole le progrès réel.

    `avertissement` est renseigné dès qu'un changement de cadence tombe dans l'une
    des périodes ou entre les deux : l'écran doit alors le montrer, jamais laisser
    l'utilisateur comparer sans le savoir.
    """
    from core import temps as temps_module

    if cadence_constante is None:
        cadence_constante = cadences.cadence_la_plus_recente(conn, ligne_id)

    def _indicateurs(bornes, cadence):
        cascade = temps_module.cascade_journaliere(
            conn, ligne_id, bornes[0], bornes[1], cadence_constante=cadence
        )
        return indicateurs.indicateurs_periode(cascade)

    resultat = {
        "periode_a": (iso(periode_a[0]), iso(periode_a[1])),
        "periode_b": (iso(periode_b[0]), iso(periode_b[1])),
        "cadence_constante": cadence_constante,
        "reelle": {"a": _indicateurs(periode_a, None), "b": _indicateurs(periode_b, None)},
    }
    if cadence_constante is not None:
        resultat["constante"] = {
            "a": _indicateurs(periode_a, cadence_constante),
            "b": _indicateurs(periode_b, cadence_constante),
        }
    else:
        resultat["constante"] = None

    # Changements de cadence couvrant l'intervalle entier, bornes comprises :
    # un changement survenu ENTRE les deux périodes fausse aussi la comparaison.
    bornes = sorted([iso(periode_a[0]), iso(periode_a[1]),
                     iso(periode_b[0]), iso(periode_b[1])])
    changements = cadences.dates_changement(conn, ligne_id, bornes[0], bornes[-1])
    resultat["changements_cadence"] = changements
    resultat["avertissement"] = (
        "La cadence de référence a changé le "
        + ", le ".join(f"{date.fromisoformat(d):%d/%m/%Y}" for d in changements)
        + ". Les deux périodes ne se comparent pas directement : un TRS plus bas "
        "peut venir d'une barre plus haute, pas d'une performance dégradée. "
        "Utilisez la lecture à cadence constante pour isoler le progrès réel."
        if changements else None
    )

    for lecture in ("reelle", "constante"):
        if resultat[lecture] is None:
            continue
        a, b = resultat[lecture]["a"]["TRS"], resultat[lecture]["b"]["TRS"]
        resultat[lecture]["ecart_trs"] = None if a is None or b is None else b - a
    return resultat


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


def evolution_produit(
    conn: sqlite3.Connection,
    ligne_id: int,
    date_debut: date | str,
    date_fin: date | str,
    periode: str = "semaine",
    article_code: str | None = None,
    famille_libelle: str | None = None,
) -> pd.DataFrame:
    """Évolution d'un article ou d'une famille, période par période.

    Expose la quantité planifiée, la quantité produite, le taux de réalisation
    et le temps théorique consommé — **jamais** de TRS, TRG ou TRE : le temps
    requis ne se ventile pas par produit (CDC §5.2 ter). Sans filtre, retourne
    l'évolution de toute la ligne, ce qui permet de situer un produit dans
    l'ensemble.
    """
    df = _production_resolue(conn, ligne_id, date_debut, date_fin)
    colonnes = ["periode", "qte_planifiee", "qte_produite",
                "temps_theorique_min", "taux_realisation"]
    if df.empty:
        return pd.DataFrame(columns=colonnes)

    df = df.copy()
    if article_code:
        df = df[df["article_code"] == article_code]
    elif famille_libelle:
        rattachements = pd.read_sql_query(
            "SELECT af.article_code, f.libelle AS famille, af.date_debut, af.date_fin"
            " FROM article_famille af JOIN famille f ON f.id = af.famille_id",
            conn,
        )
        df = historisation.resoudre_en_masse(rattachements, df, ["article_code"], "date")
        df = df[df["famille"] == famille_libelle]
    if df.empty:
        return pd.DataFrame(columns=colonnes)

    df["periode"] = cle_periode(df["date"], periode)
    df["temps_theorique_min"] = df["qte_produite"] / df["valeur_ppm"]
    groupe = df.groupby("periode", as_index=False).agg(
        qte_planifiee=("qte_planifiee", "sum"),
        qte_produite=("qte_produite", "sum"),
        temps_theorique_min=("temps_theorique_min", "sum"),
    )
    groupe["taux_realisation"] = groupe.apply(
        lambda ligne: ligne["qte_produite"] / ligne["qte_planifiee"]
        if ligne["qte_planifiee"] else None,
        axis=1,
    )
    return groupe[colonnes].sort_values("periode", ignore_index=True)


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
