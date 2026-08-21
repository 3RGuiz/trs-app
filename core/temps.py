"""Construction de la cascade des temps Tt -> To -> Tr -> Tf -> Tn -> Tu (CDC §5.1).

Unité de travail : la minute. La cadence étant en paquets PAR MINUTE,
quantité / cadence donne directement des minutes : aucun facteur 60 ici.

La cascade est calculée par jour, pour une ligne. L'agrégation (semaine, mois...)
somme ensuite les temps — jamais les taux (CDC §5.3).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from core import arrets, cadences, historisation
from core.db import iso

MINUTES_PAR_JOUR = 1440

# États d'un jour analysé. Seuls OK et FERME entrent dans les agrégations ;
# les trois autres en sont exclus (jamais comptés comme un TRS de 0 %).
ETAT_OK = "OK"
ETAT_FERME = "FERME"                          # To = 0 : fermeture prévue au calendrier
ETAT_DONNEES_MANQUANTES = "DONNEES_MANQUANTES"  # Tr > 0 mais aucune ligne importée
ETAT_HORS_SERVICE = "HORS_SERVICE"            # avant mise en service / après retrait de la ligne
ETAT_HORS_HISTORIQUE = "HORS_HISTORIQUE"      # avant la date de début d'historique exploitable


def mode_tr(conn: sqlite3.Connection, d: date | str) -> str:
    """Mode de calcul de Tr en vigueur à la date d : 'FIXE' (défaut) ou 'CALCULE'."""
    parametre = historisation.resoudre(conn, "parametre_date", {"cle": "MODE_TR"}, d)
    return parametre["valeur"] if parametre else "FIXE"


def date_debut_historique(conn: sqlite3.Connection, d: date | str) -> date | None:
    """Début d'historique exploitable en vigueur à la date d, ou None (pas d'exclusion).

    Les données antérieures restent en base mais sont exclues de toutes les
    analyses (CDC §6.4.1) : publier un TRS calculé avec des cadences supposées
    serait un chiffre faux présenté comme un fait.
    """
    parametre = historisation.resoudre(
        conn, "parametre_date", {"cle": "DATE_DEBUT_HISTORIQUE"}, d
    )
    return date.fromisoformat(parametre["valeur"]) if parametre else None


def calendrier_du_jour(conn: sqlite3.Connection, ligne_id: int, d: date | str) -> tuple[int, int]:
    """(to_min, tr_min) pour un jour : l'exception prime sur le calendrier type ;
    à défaut, le calendrier type valide à cette date ; à défaut, 0/0 (fermé)."""
    jour = iso(d)
    exception = conn.execute(
        "SELECT to_min, tr_min FROM calendrier_exception WHERE ligne_id = ? AND date = ?",
        (ligne_id, jour),
    ).fetchone()
    if exception is not None:
        return int(exception["to_min"]), int(exception["tr_min"])
    jour_semaine = date.fromisoformat(jour).weekday()
    type_jour = historisation.resoudre(
        conn, "calendrier_type", {"ligne_id": ligne_id, "jour_semaine": jour_semaine}, jour
    )
    if type_jour is not None:
        return int(type_jour["to_min"]), int(type_jour["tr_min"])
    return 0, 0


def _service_ligne(conn: sqlite3.Connection, ligne_id: int) -> tuple[date, date | None]:
    ligne = conn.execute("SELECT * FROM ligne WHERE id = ?", (ligne_id,)).fetchone()
    if ligne is None:
        from core.erreurs import ErreurMetier
        raise ErreurMetier(f"La ligne n° {ligne_id} n'existe pas.")
    debut = date.fromisoformat(ligne["date_debut"])
    fin = date.fromisoformat(ligne["date_fin"]) if ligne["date_fin"] else None
    return debut, fin


def cascade_journaliere(
    conn: sqlite3.Connection,
    ligne_id: int,
    date_debut: date | str,
    date_fin: date | str,
    cadence_constante: float | None = None,
) -> pd.DataFrame:
    """Cascade des temps par jour sur une période, pour une ligne.

    Colonnes retournées : date, etat, Tt, To, Tr, Tf, Tn, Tu, arrets_propres_min,
    arrets_hors_requis_min, qte_planifiee, qte_produite, qte_produisible_tr,
    nb_arrets_saisis, qualite_mesuree, avertissement_horodatage,
    lignes_sans_cadence.

    Les jours exclus (hors service, hors historique, données manquantes) portent
    leur état et des temps à zéro : ils ne doivent JAMAIS entrer dans une somme —
    core/agregation.py s'en charge.

    cadence_constante : recalcule toute la période avec cette cadence de référence
    au lieu de celle en vigueur à chaque date. Sert au mode « à cadence constante »
    des comparaisons (CDC §4.2), qui isole la performance réelle de l'effet d'un
    changement de référence. À n'utiliser QUE pour comparer : les indicateurs
    publiés restent ceux calculés avec la cadence en vigueur à la date.
    """
    premier = date.fromisoformat(iso(date_debut))
    dernier = date.fromisoformat(iso(date_fin))
    service_debut, service_fin = _service_ligne(conn, ligne_id)

    production = pd.read_sql_query(
        "SELECT date, ligne_id, article_code, qte_planifiee, qte_produite, qte_ensachee"
        " FROM production WHERE ligne_id = ? AND date BETWEEN ? AND ?",
        conn, params=(ligne_id, premier.isoformat(), dernier.isoformat()),
    )
    if not production.empty:
        production = cadences.resoudre_cadences(conn, production)
        production["date"] = pd.to_datetime(production["date"]).dt.date
        if cadence_constante is not None:
            if float(cadence_constante) <= 0:
                from core.erreurs import ErreurMetier
                raise ErreurMetier(
                    "La cadence de comparaison doit être supérieure à zéro."
                )
            # Les lignes sans cadence applicable restent exclues : leur donner une
            # cadence changerait le périmètre entre les deux modes et rendrait la
            # comparaison fausse. Seule la valeur de référence est remplacée.
            production.loc[production["valeur_ppm"].notna(), "valeur_ppm"] = float(
                cadence_constante
            )

    jours = []
    jour = premier
    while jour <= dernier:
        jours.append(_cascade_du_jour(
            conn, ligne_id, jour, production, service_debut, service_fin
        ))
        jour += timedelta(days=1)
    return pd.DataFrame(jours)


def _cascade_du_jour(
    conn, ligne_id, jour: date, production: pd.DataFrame,
    service_debut: date, service_fin: date | None,
) -> dict:
    base = {
        "date": jour, "etat": ETAT_OK,
        "Tt": 0.0, "To": 0.0, "Tr": 0.0, "Tf": 0.0, "Tn": 0.0, "Tu": 0.0,
        "arrets_propres_min": 0.0, "arrets_hors_requis_min": 0.0,
        "qte_planifiee": 0.0, "qte_produite": 0.0, "qte_produisible_tr": None,
        "nb_arrets_saisis": 0, "qualite_mesuree": False,
        "avertissement_horodatage": False, "lignes_sans_cadence": 0,
    }

    # Périodes hors service : exclues du calcul, pas comptées à zéro (CDC §4.1).
    if jour < service_debut or (service_fin is not None and jour > service_fin):
        base["etat"] = ETAT_HORS_SERVICE
        return base

    # Historique exploitable : les données antérieures sont stockées, pas analysées.
    debut_historique = date_debut_historique(conn, jour)
    if debut_historique is not None and jour < debut_historique:
        base["etat"] = ETAT_HORS_HISTORIQUE
        return base

    to_min, tr_min = calendrier_du_jour(conn, ligne_id, jour)
    du_jour = production[production["date"] == jour] if not production.empty else production

    if to_min == 0 and du_jour.empty:
        base["etat"] = ETAT_FERME
        base["Tt"] = float(MINUTES_PAR_JOUR)
        return base

    # Un jour requis sans aucune ligne importée est un trou de données, jamais
    # une contre-performance : état distinct, exclu des moyennes (CDC §5.4).
    if tr_min > 0 and du_jour.empty:
        base["etat"] = ETAT_DONNEES_MANQUANTES
        return base

    temps_arrets = arrets.temps_arrets_jour(conn, ligne_id, jour)
    base["nb_arrets_saisis"] = temps_arrets["nb_arrets_saisis"]
    base["avertissement_horodatage"] = temps_arrets["avertissement_horodatage"]
    base["arrets_propres_min"] = temps_arrets["ARRET_PROPRE"]
    base["arrets_hors_requis_min"] = temps_arrets["HORS_REQUIS"]

    base["Tt"] = float(MINUTES_PAR_JOUR)
    base["To"] = float(to_min)
    if mode_tr(conn, jour) == "CALCULE":
        # Tr = To - arrêts hors requis réellement déclarés.
        base["Tr"] = max(0.0, to_min - temps_arrets["HORS_REQUIS"])
    else:
        # Mode FIXE (défaut V1) : Tr vient du calendrier. Les arrêts hors requis
        # sont affichés pour information mais NON retranchés (double comptage sinon).
        base["Tr"] = float(tr_min)
    base["Tf"] = max(0.0, base["Tr"] - temps_arrets["ARRET_PROPRE"])

    if not du_jour.empty:
        sans_cadence = du_jour["valeur_ppm"].isna()
        base["lignes_sans_cadence"] = int(sans_cadence.sum())
        valides = du_jour[~sans_cadence]
        # quantité / cadence -> minutes, directement (paquets / (paquets/minute)).
        base["Tu"] = float((valides["qte_produite"] / valides["valeur_ppm"]).sum())
        base["qte_produite"] = float(valides["qte_produite"].sum())
        base["qte_planifiee"] = float(valides["qte_planifiee"].fillna(0).sum())

        # TQ mesurable seulement si le compteur d'ensacheuse est renseigné partout.
        if len(valides) and valides["qte_ensachee"].notna().all():
            base["qualite_mesuree"] = True
            base["Tn"] = float((valides["qte_ensachee"] / valides["valeur_ppm"]).sum())
        else:
            base["Tn"] = base["Tu"]

        cadences_du_jour = valides["valeur_ppm"].dropna().unique()
        if len(cadences_du_jour) == 1:
            base["qte_produisible_tr"] = float(cadences_du_jour[0]) * base["Tr"]

    return base


def jours_donnees_manquantes(df_cascade: pd.DataFrame) -> list[date]:
    """Jours requis sans données importées — à signaler en tête d'écran."""
    concernes = df_cascade[df_cascade["etat"] == ETAT_DONNEES_MANQUANTES]
    return list(concernes["date"])
