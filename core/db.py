"""Connexion SQLite, création du schéma et amorçage minimal.

La base est la mémoire de l'application (CDC §6.0). Ce module ne connaît aucun
chemin en dur : le chemin de la base est toujours passé par l'appelant, ce qui
permet de tester chaque fonction sur une base jetable.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

# Date plancher technique pour les référentiels livrés avec l'application
# (motifs génériques, mode de calcul par défaut). Ce n'est pas une donnée métier.
DATE_PLANCHER = "1900-01-01"

# Les 11 motifs globaux du référentiel AYEL & DAVIER — seuls motifs livrés avec
# l'application (CLAUDE.md règle 8). Tout le reste vient du terrain, via l'interface.
MOTIFS_AYEL_DAVIER = [
    # (code, libellé, catégorie)
    ("NETTOYAGE", "Nettoyage", "HORS_REQUIS"),
    ("SOUS_CHARGE", "Sous-charge", "HORS_REQUIS"),
    ("ESSAIS", "Essais", "HORS_REQUIS"),
    ("FORMATION", "Formation", "HORS_REQUIS"),
    ("REUNION", "Réunion", "HORS_REQUIS"),
    ("PAUSE", "Pause", "HORS_REQUIS"),
    ("MAINT_PREV", "Maintenance préventive", "HORS_REQUIS"),
    ("PANNE", "Panne", "ARRET_PROPRE"),
    ("CHGT_SERIE", "Changement de série", "ARRET_PROPRE"),
    ("REGLAGE", "Réglage", "ARRET_PROPRE"),
    ("ABS_PERSONNEL", "Absence personnel", "ARRET_PROPRE"),
]


def ouvrir_connexion(chemin: Path | str) -> sqlite3.Connection:
    """Ouvre une connexion prête à l'emploi (clés étrangères actives, busy_timeout).

    Le busy_timeout couvre les verrous transitoires provoqués par les antivirus
    sur les postes Windows (CDC §7 bis.6).
    """
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# Tables attendues par l'application : leur présence sert à savoir si la base
# est déjà initialisée, sans avoir à réécrire le schéma à chaque ouverture.
TABLES_ATTENDUES = frozenset({
    "famille", "article", "article_famille", "article_format", "ligne",
    "element_ligne", "cadence", "motif_arret", "motif_classement", "motif_element",
    "calendrier_type", "calendrier_exception", "objectif", "production", "arret",
    "import_log", "journal_referentiel", "parametre", "parametre_date",
})


def base_initialisee(conn: sqlite3.Connection) -> bool:
    """Vrai si toutes les tables attendues existent déjà."""
    presentes = {
        ligne[0] for ligne in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return TABLES_ATTENDUES.issubset(presentes)


def creer_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables si elles n'existent pas et amorce les référentiels génériques."""
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    _amorcer_motifs_generiques(conn)
    _amorcer_parametres_par_defaut(conn)
    conn.commit()


def _amorcer_motifs_generiques(conn: sqlite3.Connection) -> None:
    """Charge les 11 motifs globaux AYEL & DAVIER, une seule fois."""
    deja = conn.execute("SELECT COUNT(*) FROM motif_arret").fetchone()[0]
    if deja:
        return
    for code, libelle, categorie in MOTIFS_AYEL_DAVIER:
        cur = conn.execute(
            "INSERT INTO motif_arret (code, libelle, date_debut) VALUES (?, ?, ?)",
            (code, libelle, DATE_PLANCHER),
        )
        motif_id = cur.lastrowid
        conn.execute(
            "INSERT INTO motif_classement (motif_id, categorie, date_debut) VALUES (?, ?, ?)",
            (motif_id, categorie, DATE_PLANCHER),
        )
        # Rattachement global : proposé sur tous les éléments de la ligne.
        conn.execute(
            "INSERT INTO motif_element (motif_id, element_id, date_debut) VALUES (?, NULL, ?)",
            (motif_id, DATE_PLANCHER),
        )


def _amorcer_parametres_par_defaut(conn: sqlite3.Connection) -> None:
    """MODE_TR démarre en 'FIXE' (CDC §4.4). Les autres paramètres datés viennent de l'interface."""
    deja = conn.execute(
        "SELECT COUNT(*) FROM parametre_date WHERE cle = 'MODE_TR'"
    ).fetchone()[0]
    if not deja:
        conn.execute(
            "INSERT INTO parametre_date (cle, valeur, date_debut) VALUES ('MODE_TR', 'FIXE', ?)",
            (DATE_PLANCHER,),
        )


def ouvrir_base(chemin: Path | str) -> sqlite3.Connection:
    """Ouvre la base, en créant le schéma seulement s'il manque.

    L'interface rouvre la base à chaque affichage de page : réécrire le schéma
    à chaque fois multiplierait les écritures concurrentes sur un fichier que
    plusieurs onglets — voire plusieurs instances — peuvent partager.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = ouvrir_connexion(chemin)
    if not base_initialisee(conn):
        creer_schema(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Regroupe plusieurs écritures en une transaction : tout passe ou rien ne passe."""
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def iso(d: date | str) -> str:
    """Normalise une date (objet date ou texte ISO) vers le texte ISO stocké en base."""
    if isinstance(d, date):
        return d.isoformat()
    return date.fromisoformat(str(d)).isoformat()
