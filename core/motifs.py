"""Catalogue des motifs d'arrêt (CDC §4.3, §4.3.1).

Les motifs sont rattachés aux éléments de la ligne. Pour un élément et une date,
la liste proposée est l'union des motifs de l'élément, de ses ancêtres et des
motifs globaux — filtrée sur ce qui est en service à la date de l'arrêt.

La catégorie (HORS_REQUIS / ARRET_PROPRE) pilote la cascade des temps ; elle est
historisée : reclasser un motif ne réécrit jamais le passé. La famille
(mécanique, électrique...) ne sert qu'à l'analyse.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
import unicodedata
from datetime import date

from core import elements, historisation
from core.db import iso, transaction
from core.erreurs import ErreurMetier, MotifInterdit, SuppressionInterdite

# Les écarts de cadence ne se saisissent JAMAIS comme motif d'arrêt : ils sont
# calculés par différence et apparaissent dans TP. Un motif de ce type serait
# compté deux fois (CDC §4.3). À ne pas confondre avec la sous-charge (pas assez
# de commandes), qui est un arrêt hors requis légitime.
_TERMES_SOUS_CADENCE = (
    "sous-cadence", "sous cadence", "souscadence",
    "bridage", "bride", "ralenti", "ralentissement", "cadence reduite",
)


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation — pour comparer des libellés."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", texte.lower()).strip()


def verifier_libelle(libelle: str) -> None:
    """Refuse un libellé évoquant une sous-cadence ou un bridage."""
    normalise = _normaliser(libelle)
    for terme in _TERMES_SOUS_CADENCE:
        if _normaliser(terme) in normalise:
            raise MotifInterdit(
                f"Le motif « {libelle} » décrit une sous-cadence ou un bridage. "
                "Ce type de perte n'est jamais saisi comme arrêt : il est calculé "
                "par différence et apparaît dans le taux de performance (TP). "
                "Le saisir en arrêt le compterait deux fois. "
                "S'il s'agit d'un manque de commandes, utilisez « Sous-charge »."
            )


def libelles_proches(
    conn: sqlite3.Connection, libelle: str, seuil: float = 0.72
) -> list[dict]:
    """Motifs existants dont le libellé ressemble à celui proposé.

    À afficher avant toute création : sans cela, on se retrouve en deux ans avec
    « bourrage », « Bourrage » et « bourage », et le Pareto ne veut plus rien dire.
    """
    reference = _normaliser(libelle)
    proches = []
    for ligne in conn.execute("SELECT * FROM motif_arret").fetchall():
        ressemblance = difflib.SequenceMatcher(
            None, reference, _normaliser(ligne["libelle"])
        ).ratio()
        if ressemblance >= seuil:
            proches.append({**dict(ligne), "ressemblance": round(ressemblance, 2)})
    return sorted(proches, key=lambda m: -m["ressemblance"])


def creer_motif(
    conn: sqlite3.Connection,
    code: str,
    libelle: str,
    categorie: str,
    date_debut: date | str,
    commentaire: str,
    auteur: str,
    famille: str | None = None,
    element_id: int | None = None,
) -> int:
    """Crée un motif et le rattache à un élément (ou globalement si element_id est None).

    C'est la fonction derrière le bouton « Ajouter un motif » de l'écran de saisie.
    """
    verifier_libelle(libelle)
    if categorie not in ("HORS_REQUIS", "ARRET_PROPRE"):
        raise ErreurMetier(
            "La catégorie d'un motif est obligatoire : « ARRET_PROPRE » (aléa subi, "
            "retranché du temps requis) ou « HORS_REQUIS » (retranché du temps d'ouverture)."
        )
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO motif_arret (code, libelle, date_debut) VALUES (?, ?, ?)",
            (code, libelle, iso(date_debut)),
        )
        motif_id = cur.lastrowid
    historisation.cloturer_et_inserer(
        conn, "motif_classement", {"motif_id": motif_id},
        {"categorie": categorie, "famille": famille},
        date_debut, commentaire, auteur,
    )
    historisation.cloturer_et_inserer(
        conn, "motif_element", {"motif_id": motif_id, "element_id": element_id},
        {}, date_debut, commentaire, auteur,
    )
    return motif_id


def categorie_motif(conn: sqlite3.Connection, motif_id: int, d: date | str) -> str | None:
    """Catégorie du motif en vigueur à la date d — celle qui pilote la cascade."""
    classement = historisation.resoudre(conn, "motif_classement", {"motif_id": motif_id}, d)
    return classement["categorie"] if classement else None


def reclasser_motif(
    conn: sqlite3.Connection,
    motif_id: int,
    categorie: str,
    date_effet: date | str,
    commentaire: str,
    auteur: str,
    famille: str | None = None,
) -> int:
    """Change la catégorie d'un motif à partir d'une date d'effet, sans toucher au passé."""
    if categorie not in ("HORS_REQUIS", "ARRET_PROPRE"):
        raise ErreurMetier("Catégorie inconnue : « HORS_REQUIS » ou « ARRET_PROPRE » attendu.")
    if famille is None:
        courant = historisation.resoudre(conn, "motif_classement", {"motif_id": motif_id}, date_effet)
        famille = courant["famille"] if courant else None
    return historisation.cloturer_et_inserer(
        conn, "motif_classement", {"motif_id": motif_id},
        {"categorie": categorie, "famille": famille},
        date_effet, commentaire, auteur,
    )


def motifs_proposes(
    conn: sqlite3.Connection, element_id: int | None, d: date | str
) -> list[dict]:
    """Liste des motifs proposés pour un élément à une date donnée.

    Union : motifs de l'élément + motifs de ses ancêtres + motifs globaux,
    le tout filtré sur les motifs et rattachements en service à la date.
    """
    jour = iso(d)
    cibles: list[int | None] = [None]
    if element_id is not None:
        cibles = [element_id, *elements.ancetres(conn, element_id), None]

    marques = ", ".join("?" for e in cibles if e is not None)
    condition = "me.element_id IS NULL"
    parametres: list = []
    if marques:
        condition += f" OR me.element_id IN ({marques})"
        parametres = [e for e in cibles if e is not None]

    lignes = conn.execute(
        f"""
        SELECT DISTINCT m.*
        FROM motif_arret m
        JOIN motif_element me ON me.motif_id = m.id
        WHERE ({condition})
          AND me.date_debut <= ? AND (me.date_fin IS NULL OR me.date_fin >= ?)
          AND m.date_debut  <= ? AND (m.date_fin  IS NULL OR m.date_fin  >= ?)
        ORDER BY m.libelle
        """,
        parametres + [jour, jour, jour, jour],
    ).fetchall()
    return [dict(ligne) for ligne in lignes]


def retirer_motif(
    conn: sqlite3.Connection,
    motif_id: int,
    date_fin: date | str,
    commentaire: str,
    auteur: str,
) -> None:
    """Retire un motif du catalogue : il n'est plus proposé à la saisie mais reste
    lisible sur tous les arrêts passés. Un motif utilisé ne se supprime jamais."""
    motif = conn.execute("SELECT * FROM motif_arret WHERE id = ?", (motif_id,)).fetchone()
    if motif is None:
        raise ErreurMetier(f"Le motif n° {motif_id} n'existe pas.")
    with transaction(conn):
        conn.execute(
            "UPDATE motif_arret SET date_fin = ? WHERE id = ?", (iso(date_fin), motif_id)
        )
        conn.execute(
            "INSERT INTO journal_referentiel"
            " (table_cible, cle_metier, action, ancienne_valeur, nouvelle_valeur,"
            "  date_effet, commentaire, auteur)"
            " VALUES ('motif_arret', ?, 'CLOTURE', ?, ?, ?, ?, ?)",
            (motif["code"], json.dumps({"libelle": motif["libelle"]}, ensure_ascii=False),
             json.dumps({"date_fin": iso(date_fin)}, ensure_ascii=False),
             iso(date_fin), commentaire, auteur),
        )


def supprimer_motif(conn: sqlite3.Connection, motif_id: int) -> None:
    """Suppression physique, uniquement si aucun arrêt n'utilise le motif."""
    utilise = conn.execute(
        "SELECT COUNT(*) FROM arret WHERE motif_id = ?", (motif_id,)
    ).fetchone()[0]
    if utilise:
        raise SuppressionInterdite(
            f"Ce motif est utilisé par {utilise} arrêt(s) : il ne peut pas être supprimé. "
            "Utilisez « Retirer » pour qu'il ne soit plus proposé à la saisie."
        )
    with transaction(conn):
        conn.execute("DELETE FROM motif_element WHERE motif_id = ?", (motif_id,))
        conn.execute("DELETE FROM motif_classement WHERE motif_id = ?", (motif_id,))
        conn.execute("DELETE FROM motif_arret WHERE id = ?", (motif_id,))


def fusionner_motifs(
    conn: sqlite3.Connection,
    motif_garde_id: int,
    motif_absorbe_id: int,
    commentaire: str,
    auteur: str,
) -> int:
    """Fusionne deux motifs doublons : les arrêts du motif absorbé sont réaffectés
    au motif conservé, le motif absorbé est retiré, l'opération est tracée au journal.

    Aucun indicateur de la cascade ne doit bouger — seule la lecture du Pareto change.
    Retourne le nombre d'arrêts réaffectés.
    """
    if motif_garde_id == motif_absorbe_id:
        raise ErreurMetier("Choisissez deux motifs différents pour la fusion.")
    garde = conn.execute("SELECT * FROM motif_arret WHERE id = ?", (motif_garde_id,)).fetchone()
    absorbe = conn.execute("SELECT * FROM motif_arret WHERE id = ?", (motif_absorbe_id,)).fetchone()
    if garde is None or absorbe is None:
        raise ErreurMetier("L'un des deux motifs à fusionner n'existe pas.")

    with transaction(conn):
        cur = conn.execute(
            "UPDATE arret SET motif_id = ? WHERE motif_id = ?",
            (motif_garde_id, motif_absorbe_id),
        )
        reaffectes = cur.rowcount
        conn.execute(
            "UPDATE motif_arret SET date_fin = ? WHERE id = ? AND date_fin IS NULL",
            (date.today().isoformat(), motif_absorbe_id),
        )
        conn.execute(
            "INSERT INTO journal_referentiel"
            " (table_cible, cle_metier, action, ancienne_valeur, nouvelle_valeur,"
            "  date_effet, commentaire, auteur)"
            " VALUES ('motif_arret', ?, 'CORRECTION', ?, ?, ?, ?, ?)",
            (f"{absorbe['code']} -> {garde['code']}",
             json.dumps({"motif_absorbe": absorbe["libelle"],
                         "arrets_reaffectes": reaffectes}, ensure_ascii=False),
             json.dumps({"motif_conserve": garde["libelle"]}, ensure_ascii=False),
             date.today().isoformat(), commentaire, auteur),
        )
    return reaffectes
