"""Arborescence des éléments de la ligne (CDC §4.1, §4.6.1).

Les éléments (zones, machines, organes) servent à ANALYSER l'origine des arrêts,
jamais à calculer la cascade des temps : déplacer un arrêt d'un élément à un autre
ne change aucun indicateur.

Gestes offerts à l'utilisateur : ajouter, retirer (le geste par défaut), remplacer,
déplacer, et supprimer physiquement — ce dernier uniquement quand c'est sans
conséquence (aucun arrêt rattaché, aucun descendant). Jamais de suppression en
cascade, jamais de réaffectation automatique des arrêts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from core.db import iso, transaction
from core.erreurs import ErreurMetier, SuppressionInterdite

TYPES_VALIDES = ("ZONE", "EQUIPEMENT", "ORGANE")


def _element(conn: sqlite3.Connection, element_id: int) -> sqlite3.Row:
    ligne = conn.execute(
        "SELECT * FROM element_ligne WHERE id = ?", (element_id,)
    ).fetchone()
    if ligne is None:
        raise ErreurMetier(f"L'élément n° {element_id} n'existe pas.")
    return ligne


def _journaliser(conn, action: str, cle: str, ancienne, nouvelle,
                 date_effet: str, commentaire: str, auteur: str) -> None:
    conn.execute(
        "INSERT INTO journal_referentiel"
        " (table_cible, cle_metier, action, ancienne_valeur, nouvelle_valeur,"
        "  date_effet, commentaire, auteur) VALUES ('element_ligne', ?, ?, ?, ?, ?, ?, ?)",
        (cle, action,
         json.dumps(ancienne, ensure_ascii=False) if ancienne is not None else None,
         json.dumps(nouvelle, ensure_ascii=False) if nouvelle is not None else None,
         date_effet, commentaire, auteur),
    )


def ajouter_element(
    conn: sqlite3.Connection,
    ligne_id: int,
    parent_id: int | None,
    code: str,
    libelle: str,
    type_element: str,
    date_debut: date | str,
    ordre: int | None = None,
    remplace_id: int | None = None,
    commentaire: str = "Création depuis l'interface",
    auteur: str = "utilisateur",
) -> int:
    """Crée un élément à n'importe quel niveau, avec sa date de mise en service.

    Le chemin matérialisé (suite des identifiants ancêtres, ex. '/3/12/47/') est
    calculé ici et permet d'agréger les arrêts sous n'importe quel niveau sans
    requête récursive.
    """
    if type_element not in TYPES_VALIDES:
        raise ErreurMetier(
            f"Type d'élément inconnu : « {type_element} ». "
            f"Types possibles : {', '.join(TYPES_VALIDES)}."
        )
    chemin_parent = "/"
    if parent_id is not None:
        parent = _element(conn, parent_id)
        if parent["ligne_id"] != ligne_id:
            raise ErreurMetier("Le parent choisi appartient à une autre ligne.")
        chemin_parent = parent["chemin"]

    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO element_ligne"
            " (ligne_id, parent_id, code, libelle, type, ordre, chemin, remplace_id, date_debut)"
            " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)",
            (ligne_id, parent_id, code, libelle, type_element, ordre,
             remplace_id, iso(date_debut)),
        )
        element_id = cur.lastrowid
        chemin = f"{chemin_parent}{element_id}/"
        conn.execute(
            "UPDATE element_ligne SET chemin = ? WHERE id = ?", (chemin, element_id)
        )
        _journaliser(
            conn, "CREATION", code, None,
            {"libelle": libelle, "type": type_element, "parent_id": parent_id},
            iso(date_debut), commentaire, auteur,
        )
    return element_id


def descendants(conn: sqlite3.Connection, element_id: int) -> list[dict]:
    """Tous les descendants d'un élément, via le chemin matérialisé."""
    element = _element(conn, element_id)
    lignes = conn.execute(
        "SELECT * FROM element_ligne WHERE ligne_id = ? AND chemin LIKE ? AND id != ?",
        (element["ligne_id"], element["chemin"] + "%", element_id),
    ).fetchall()
    return [dict(ligne) for ligne in lignes]


def ancetres(conn: sqlite3.Connection, element_id: int) -> list[int]:
    """Identifiants des ancêtres, du plus haut au plus proche, hors l'élément lui-même."""
    element = _element(conn, element_id)
    ids = [int(morceau) for morceau in element["chemin"].strip("/").split("/") if morceau]
    return ids[:-1]


def nb_arrets(conn: sqlite3.Connection, element_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM arret WHERE element_id = ?", (element_id,)
    ).fetchone()[0]


def retirer_element(
    conn: sqlite3.Connection,
    element_id: int,
    date_fin: date | str,
    commentaire: str = "Retrait du service",
    auteur: str = "utilisateur",
) -> None:
    """Retire un élément du service — le geste par défaut, jamais destructif.

    L'élément disparaît des listes de saisie à partir de cette date mais reste
    parfaitement lisible dans l'historique : les analyses passées sont inchangées.
    """
    element = _element(conn, element_id)
    if element["date_fin"] is not None:
        raise ErreurMetier(
            f"L'élément « {element['libelle']} » est déjà retiré du service "
            f"depuis le {element['date_fin']}."
        )
    with transaction(conn):
        conn.execute(
            "UPDATE element_ligne SET date_fin = ? WHERE id = ?",
            (iso(date_fin), element_id),
        )
        _journaliser(
            conn, "CLOTURE", element["code"],
            {"libelle": element["libelle"]}, {"date_fin": iso(date_fin)},
            iso(date_fin), commentaire, auteur,
        )


def supprimer_element(conn: sqlite3.Connection, element_id: int) -> None:
    """Suppression physique — uniquement quand c'est sans conséquence.

    Autorisée seulement si l'élément n'a aucun arrêt rattaché et aucun descendant
    (cas d'une faute de frappe ou d'un doublon). Sinon, erreur explicite qui
    propose le retrait. Jamais de suppression en cascade.
    """
    element = _element(conn, element_id)
    arrets = nb_arrets(conn, element_id)
    enfants = descendants(conn, element_id)
    if arrets or enfants:
        raisons = []
        if arrets:
            raisons.append(f"{arrets} arrêt(s) rattaché(s)")
        if enfants:
            raisons.append(f"{len(enfants)} élément(s) descendant(s)")
        raise SuppressionInterdite(
            f"Impossible de supprimer « {element['libelle']} » : {' et '.join(raisons)}. "
            "Le supprimer rendrait ces données inexploitables. "
            "Utilisez plutôt « Retirer du service » avec une date de fin."
        )
    with transaction(conn):
        conn.execute("DELETE FROM motif_element WHERE element_id = ?", (element_id,))
        conn.execute("DELETE FROM element_ligne WHERE id = ?", (element_id,))
        _journaliser(
            conn, "CORRECTION", element["code"],
            {"libelle": element["libelle"]}, None,
            date.today().isoformat(),
            "Suppression physique d'un élément sans arrêt ni descendant", "utilisateur",
        )


def remplacer_element(
    conn: sqlite3.Connection,
    ancien_id: int,
    code: str,
    libelle: str,
    date_effet: date | str,
    commentaire: str = "Remplacement d'équipement",
    auteur: str = "utilisateur",
) -> int:
    """Remplace une machine par une nouvelle, en une opération.

    Clôture l'ancienne la veille de la prise d'effet, crée la nouvelle à la même
    position dans l'arbre et chaîne la lignée par remplace_id — ce qui permet de
    comparer les générations d'équipements.
    """
    ancien = _element(conn, ancien_id)
    veille = date.fromisoformat(iso(date_effet)) - timedelta(days=1)
    retirer_element(conn, ancien_id, veille, commentaire, auteur)
    return ajouter_element(
        conn,
        ligne_id=ancien["ligne_id"],
        parent_id=ancien["parent_id"],
        code=code,
        libelle=libelle,
        type_element=ancien["type"],
        date_debut=date_effet,
        ordre=ancien["ordre"],
        remplace_id=ancien_id,
        commentaire=commentaire,
        auteur=auteur,
    )


def deplacer_element(
    conn: sqlite3.Connection,
    element_id: int,
    nouveau_parent_id: int | None,
    commentaire: str = "Déplacement dans l'arborescence",
    auteur: str = "utilisateur",
) -> None:
    """Change le parent d'un élément et recalcule les chemins de tous ses
    descendants, dans la même transaction. Aucun indicateur ne doit en bouger."""
    element = _element(conn, element_id)
    ancien_chemin = element["chemin"]

    chemin_parent = "/"
    if nouveau_parent_id is not None:
        parent = _element(conn, nouveau_parent_id)
        if parent["ligne_id"] != element["ligne_id"]:
            raise ErreurMetier("Le nouveau parent appartient à une autre ligne.")
        if parent["chemin"].startswith(ancien_chemin):
            raise ErreurMetier(
                "Impossible de déplacer un élément sous l'un de ses propres descendants."
            )
        chemin_parent = parent["chemin"]

    nouveau_chemin = f"{chemin_parent}{element_id}/"
    with transaction(conn):
        conn.execute(
            "UPDATE element_ligne SET parent_id = ?, chemin = ? WHERE id = ?",
            (nouveau_parent_id, nouveau_chemin, element_id),
        )
        # Recalcul du chemin de tous les descendants : préfixe remplacé.
        conn.execute(
            "UPDATE element_ligne SET chemin = ? || substr(chemin, ?)"
            " WHERE ligne_id = ? AND chemin LIKE ? AND id != ?",
            (nouveau_chemin, len(ancien_chemin) + 1,
             element["ligne_id"], ancien_chemin + "%", element_id),
        )
        _journaliser(
            conn, "CORRECTION", element["code"],
            {"chemin": ancien_chemin}, {"chemin": nouveau_chemin},
            date.today().isoformat(), commentaire, auteur,
        )


def elements_en_service(
    conn: sqlite3.Connection, ligne_id: int, d: date | str
) -> list[dict]:
    """Les éléments en service à une date donnée, dans l'ordre de l'arbre."""
    jour = iso(d)
    lignes = conn.execute(
        "SELECT * FROM element_ligne WHERE ligne_id = ? AND date_debut <= ?"
        " AND (date_fin IS NULL OR date_fin >= ?) ORDER BY chemin, ordre",
        (ligne_id, jour, jour),
    ).fetchall()
    return [dict(ligne) for ligne in lignes]
