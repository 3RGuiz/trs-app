"""Arrêts de ligne : union des intervalles et catégorisation (CDC §4.6).

Deux règles structurantes :

- seuls les arrêts à arrete_ligne = 1 entrent dans la cascade ; ceux absorbés par
  un tampon sont conservés pour le Pareto et n'affectent aucun temps ;
- les arrêts simultanés ne s'additionnent pas : deux sections en panne en même
  temps n'arrêtent la ligne qu'une fois. La cascade utilise la durée de l'UNION
  des intervalles, jamais la somme des durées déclarées.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd

from core import motifs
from core.db import iso


def duree_union(intervalles: list[tuple[datetime, datetime]]) -> float:
    """Durée totale couverte par les intervalles, en minutes, chevauchements fusionnés.

    Tri par début, fusion des intervalles qui se recouvrent, somme des longueurs.
    """
    if not intervalles:
        return 0.0
    tries = sorted(intervalles, key=lambda iv: iv[0])
    total = 0.0
    debut_courant, fin_courante = tries[0]
    for debut, fin in tries[1:]:
        if debut <= fin_courante:
            fin_courante = max(fin_courante, fin)
        else:
            total += (fin_courante - debut_courant).total_seconds() / 60
            debut_courant, fin_courante = debut, fin
    total += (fin_courante - debut_courant).total_seconds() / 60
    return total


def _en_datetime(valeur) -> datetime | None:
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur
    return datetime.fromisoformat(str(valeur))


def duree_arrets_ligne(arrets: list[dict]) -> tuple[float, bool]:
    """Durée d'arrêt de ligne d'un ensemble d'arrêts, en minutes.

    Utilise l'union des intervalles quand tous les horodatages sont présents.
    Repli si des horodatages manquent : somme des durées déclarées, avec un
    indicateur d'avertissement (les chevauchements ne peuvent pas être détectés).
    Ce repli n'est jamais silencieux : le second élément du retour vaut True.
    """
    if not arrets:
        return 0.0, False
    intervalles = []
    horodatage_manquant = False
    somme = 0.0
    for arret in arrets:
        debut = _en_datetime(arret.get("debut"))
        fin = _en_datetime(arret.get("fin"))
        somme += float(arret["duree_min"])
        if debut is None or fin is None:
            horodatage_manquant = True
        else:
            intervalles.append((debut, fin))
    if horodatage_manquant:
        return somme, True
    return duree_union(intervalles), False


def arrets_du_jour(
    conn: sqlite3.Connection, ligne_id: int, d: date | str
) -> list[dict]:
    """Tous les arrêts d'un jour, enrichis de la catégorie du motif en vigueur
    à la date de l'arrêt (le reclassement ultérieur d'un motif ne touche pas au passé)."""
    jour = iso(d)
    lignes = conn.execute(
        "SELECT * FROM arret WHERE ligne_id = ? AND date = ?", (ligne_id, jour)
    ).fetchall()
    resultat = []
    for ligne in lignes:
        arret = dict(ligne)
        arret["categorie"] = motifs.categorie_motif(conn, arret["motif_id"], jour)
        resultat.append(arret)
    return resultat


def temps_arrets_jour(
    conn: sqlite3.Connection, ligne_id: int, d: date | str
) -> dict:
    """Temps d'arrêt de ligne du jour, par catégorie, en minutes.

    Union calculée séparément pour chaque catégorie (HORS_REQUIS d'une part,
    ARRET_PROPRE de l'autre), sur les seuls arrêts à arrete_ligne = 1,
    tous éléments confondus.

    Retourne : {'ARRET_PROPRE': min, 'HORS_REQUIS': min,
                'avertissement_horodatage': bool, 'nb_arrets_saisis': int}
    """
    tous = arrets_du_jour(conn, ligne_id, d)
    resultat = {"ARRET_PROPRE": 0.0, "HORS_REQUIS": 0.0,
                "avertissement_horodatage": False, "nb_arrets_saisis": len(tous)}
    for categorie in ("ARRET_PROPRE", "HORS_REQUIS"):
        concernes = [
            a for a in tous
            if a["arrete_ligne"] == 1 and a["categorie"] == categorie
        ]
        duree, avertissement = duree_arrets_ligne(concernes)
        resultat[categorie] = duree
        resultat["avertissement_horodatage"] |= avertissement
    return resultat


def verifier_element_en_service(
    conn: sqlite3.Connection, element_id: int | None, d: date | str
) -> str | None:
    """Alerte si l'élément d'origine n'était pas en service à la date de l'arrêt.

    Non bloquant (CDC §4.6) : mieux vaut conserver l'arrêt avec une alerte que
    perdre l'information. Signale un matériel déposé, pas encore installé, ou
    une date d'effet mal saisie au référentiel.
    """
    if element_id is None:
        return None
    element = conn.execute(
        "SELECT libelle, date_debut, date_fin FROM element_ligne WHERE id = ?",
        (element_id,),
    ).fetchone()
    if element is None:
        return f"L'élément n° {element_id} n'existe pas."
    jour = iso(d)
    if jour < element["date_debut"]:
        return (
            f"« {element['libelle']} » n'était pas encore en service le "
            f"{date.fromisoformat(jour):%d/%m/%Y} (mise en service le "
            f"{date.fromisoformat(element['date_debut']):%d/%m/%Y})."
        )
    if element["date_fin"] and jour > element["date_fin"]:
        return (
            f"« {element['libelle']} » était déjà retiré du service le "
            f"{date.fromisoformat(jour):%d/%m/%Y} (retrait le "
            f"{date.fromisoformat(element['date_fin']):%d/%m/%Y})."
        )
    return None


def _verifier_capacite_du_jour(
    conn: sqlite3.Connection, ligne_id: int, d: date | str,
    categorie: str | None, arrete_ligne: int, duree_ajoutee: float,
) -> None:
    """Refuse un arrêt qui ferait dépasser le temps disponible du jour (CDC §5.4).

    Les arrêts propres ne peuvent pas excéder le temps requis, ni les arrêts hors
    requis le temps d'ouverture : au-delà, c'est une erreur de saisie ou de
    calendrier, et la cascade produirait un temps de fonctionnement négatif.
    Le contrôle porte sur l'UNION des arrêts déjà saisis plus celui-ci, et ne
    concerne que les arrêts qui ont réellement stoppé la ligne.
    """
    from core.erreurs import ErreurMetier
    from core import temps as temps_module

    if arrete_ligne != 1 or categorie is None:
        return
    to_min, tr_min = temps_module.calendrier_du_jour(conn, ligne_id, d)
    plafond, libelle_plafond = (
        (tr_min, "temps requis") if categorie == "ARRET_PROPRE"
        else (to_min, "temps d'ouverture")
    )
    if plafond == 0:
        return   # journée fermée : le calendrier est à corriger, pas l'arrêt
    deja = temps_arrets_jour(conn, ligne_id, d)[categorie]
    if deja + duree_ajoutee > plafond:
        raise ErreurMetier(
            f"Cet arrêt porterait le total des arrêts du "
            f"{date.fromisoformat(iso(d)):%d/%m/%Y} à "
            f"{deja + duree_ajoutee:.0f} minutes, au-delà du {libelle_plafond} "
            f"de la journée ({plafond} minutes). Vérifiez l'horaire saisi, "
            "ou le calendrier de cette journée depuis le référentiel."
        )


def saisir_arret(
    conn: sqlite3.Connection,
    ligne_id: int,
    d: date | str,
    motif_id: int,
    duree_min: float | None = None,
    debut: datetime | str | None = None,
    fin: datetime | str | None = None,
    element_id: int | None = None,
    arrete_ligne: int = 1,
    commentaire: str | None = None,
    import_id: int | None = None,
    controler_capacite: bool = True,
) -> int:
    """Enregistre un arrêt. La durée est déduite des horodatages quand ils existent.

    Retourne l'identifiant de l'arrêt créé. Lève une erreur métier si la fin
    précède le début, ou si le cumul dépasserait le temps disponible du jour.
    L'alerte « élément hors service » s'obtient séparément par
    verifier_element_en_service() : elle n'empêche pas la saisie.
    """
    from core.erreurs import ErreurMetier

    debut_dt, fin_dt = _en_datetime(debut), _en_datetime(fin)
    if debut_dt and fin_dt:
        if fin_dt <= debut_dt:
            raise ErreurMetier(
                "La fin de l'arrêt doit être postérieure à son début "
                f"({debut_dt:%H:%M} -> {fin_dt:%H:%M})."
            )
        duree_calculee = (fin_dt - debut_dt).total_seconds() / 60
        if duree_min is None:
            duree_min = duree_calculee
    if duree_min is None:
        raise ErreurMetier(
            "Un arrêt doit porter soit ses horodatages de début et de fin, "
            "soit à défaut une durée en minutes."
        )
    if duree_min < 0:
        raise ErreurMetier("La durée d'un arrêt ne peut pas être négative.")

    if controler_capacite:
        from core import motifs as motifs_module
        _verifier_capacite_du_jour(
            conn, ligne_id, d,
            motifs_module.categorie_motif(conn, motif_id, d),
            arrete_ligne, float(duree_min),
        )

    cur = conn.execute(
        "INSERT INTO arret (date, ligne_id, element_id, motif_id, debut, fin,"
        " duree_min, arrete_ligne, commentaire, import_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (iso(d), ligne_id, element_id, motif_id,
         debut_dt.isoformat(sep=" ") if debut_dt else None,
         fin_dt.isoformat(sep=" ") if fin_dt else None,
         float(duree_min), int(arrete_ligne), commentaire, import_id),
    )
    conn.commit()
    return cur.lastrowid


def pareto(
    conn: sqlite3.Connection,
    ligne_id: int,
    date_debut: date | str,
    date_fin: date | str,
    par: str = "motif",
) -> pd.DataFrame:
    """Pareto des arrêts sur une période : durée cumulée et nombre d'arrêts.

    par = 'motif', 'element' ou 'zone'. Tous les arrêts sont comptés, y compris
    ceux à arrete_ligne = 0 (absorbés) : le Pareto sert à chercher les causes,
    pas à calculer la cascade. Les arrêts sans élément d'origine apparaissent
    sous « Origine non renseignée » — c'est plus honnête que de les attribuer
    d'office à une machine.
    """
    df = pd.read_sql_query(
        "SELECT a.*, m.libelle AS motif_libelle, e.libelle AS element_libelle,"
        "       e.chemin AS element_chemin"
        " FROM arret a"
        " JOIN motif_arret m ON m.id = a.motif_id"
        " LEFT JOIN element_ligne e ON e.id = a.element_id"
        " WHERE a.ligne_id = ? AND a.date BETWEEN ? AND ?",
        conn, params=(ligne_id, iso(date_debut), iso(date_fin)),
    )
    if df.empty:
        return pd.DataFrame(columns=["libelle", "duree_min", "nb_arrets"])

    if par == "motif":
        df["libelle"] = df["motif_libelle"]
    elif par == "element":
        df["libelle"] = df["element_libelle"].fillna("Origine non renseignée")
    elif par == "zone":
        racines = {
            str(ligne["id"]): ligne["libelle"]
            for ligne in conn.execute(
                "SELECT id, libelle FROM element_ligne"
                " WHERE ligne_id = ? AND parent_id IS NULL", (ligne_id,)
            ).fetchall()
        }
        def zone_de(chemin):
            if not isinstance(chemin, str) or not chemin.strip("/"):
                return "Origine non renseignée"
            return racines.get(chemin.strip("/").split("/")[0], "Origine non renseignée")
        df["libelle"] = df["element_chemin"].map(zone_de)
    else:
        raise ValueError("par doit valoir 'motif', 'element' ou 'zone'")

    groupe = (
        df.groupby("libelle", as_index=False)
        .agg(duree_min=("duree_min", "sum"), nb_arrets=("id", "count"))
        .sort_values("duree_min", ascending=False, ignore_index=True)
    )
    return groupe
