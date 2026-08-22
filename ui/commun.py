"""Éléments partagés par toutes les pages : connexion, erreurs, fraîcheur.

Streamlit est configuré avec showErrorDetails = "none" : rien ne s'affiche de
lui-même en cas d'erreur. Chaque page doit donc rattraper ses erreurs et les
expliquer en français. Le détail technique part en console, jamais à l'écran.
"""

from __future__ import annotations

import logging
import sqlite3
import tomllib
from datetime import date
from pathlib import Path

import streamlit as st

from core import db
from core.erreurs import ErreurMetier

RACINE = Path(__file__).parent.parent
journal = logging.getLogger("trs")


def signaler(message: str, erreur: Exception | None = None) -> None:
    """Affiche une erreur compréhensible et interrompt la page proprement.

    Ne jamais appeler depuis l'intérieur d'un bloc try surveillé par un except
    large : st.stop() lève une exception interne à Streamlit.
    """
    if erreur is not None:
        journal.exception(message)
    st.error(message)
    st.stop()


def chemin_base() -> Path:
    """Chemin de la base, lu dans config.toml — jamais écrit en dur."""
    config = RACINE / "config.toml"
    if config.exists():
        contenu = tomllib.loads(config.read_text(encoding="utf-8"))
        return RACINE / contenu.get("base", {}).get("chemin", "data/trs.db")
    return RACINE / "data" / "trs.db"


def ouvrir() -> sqlite3.Connection:
    """Ouvre la base en expliquant l'échec en français plutôt qu'en stack trace."""
    try:
        return db.ouvrir_base(chemin_base())
    except tomllib.TOMLDecodeError as erreur:
        signaler(
            "Le fichier de configuration config.toml est illisible. Corrigez-le "
            "ou supprimez-le pour revenir aux valeurs par défaut.", erreur,
        )
    except ErreurMetier as erreur:
        signaler(str(erreur), erreur)
    except Exception as erreur:
        signaler(
            f"Impossible d'ouvrir la base de données ({chemin_base()}). Vérifiez "
            "que le fichier existe, qu'il n'est pas ouvert par un autre programme, "
            "et que le dossier est accessible.", erreur,
        )


def ligne_active(conn: sqlite3.Connection) -> dict | None:
    """Première ligne en service, ou None si le référentiel est vide."""
    ligne = conn.execute(
        "SELECT * FROM ligne WHERE date_fin IS NULL ORDER BY code LIMIT 1"
    ).fetchone()
    return dict(ligne) if ligne else None


def lignes_disponibles(conn: sqlite3.Connection) -> list[dict]:
    """Toutes les lignes en service, dans l'ordre du référentiel."""
    return [dict(l) for l in conn.execute(
        "SELECT * FROM ligne WHERE date_fin IS NULL ORDER BY id"
    ).fetchall()]


def message_base_vide() -> None:
    st.info(
        "Aucune ligne de production n'est encore déclarée. Créez-la depuis la "
        "page Référentiel, avec ses cadences et son calendrier. Pour essayer "
        "l'application sans données réelles : `python generer_donnees_test.py`."
    )
    st.stop()


def selecteur_ligne(
    conn: sqlite3.Connection, lignes: list[dict], cle: str = "ligne"
) -> dict:
    """Choix de la ligne analysée, mémorisé entre les écrans.

    Une seule ligne : pas de widget, le titre suffit. Plusieurs : le choix
    doit être visible en permanence, car tous les chiffres en dépendent.
    """
    if len(lignes) == 1:
        st.caption(f"Ligne mesurée : {lignes[0]['libelle']}")
        return lignes[0]

    identifiants = [l["id"] for l in lignes]
    if st.session_state.get("ligne_analysee") not in identifiants:
        st.session_state.ligne_analysee = identifiants[0]

    libelles = {l["id"]: l["libelle"] for l in lignes}
    choisi = st.selectbox(
        "Ligne analysée", identifiants,
        index=identifiants.index(st.session_state.ligne_analysee),
        format_func=lambda i: libelles[i], key=f"{cle}_selecteur_ligne",
    )
    st.session_state.ligne_analysee = choisi
    return next(l for l in lignes if l["id"] == choisi)


def selecteur_produit(
    conn: sqlite3.Connection, ligne_id: int, cle: str = "produit"
) -> tuple[str | None, str | None, str]:
    """Choix du périmètre analysé : toute la ligne, une famille, un article.

    Retourne (article_code, famille_libelle, libellé du périmètre). Les deux
    premiers valent None pour la ligne entière.

    Ce sélecteur ne donne jamais accès à un TRS par produit : le temps requis ne
    se ventile pas par article (CDC §5.2 ter). Il ouvre l'accès aux quantités,
    au taux de réalisation et au temps de capacité mobilisé, qui eux se
    ventilent exactement.
    """
    # Libellés chargés en une fois : les résoudre dans le format_func relancerait
    # une requête par option à chaque rendu.
    libelles_articles = {
        a["code"]: a["libelle"] for a in conn.execute(
            "SELECT DISTINCT a.code, a.libelle FROM article a"
            " JOIN production p ON p.article_code = a.code"
            " WHERE p.ligne_id = ? ORDER BY a.code", (ligne_id,),
        ).fetchall()
    }
    articles = list(libelles_articles)
    familles = [f[0] for f in conn.execute(
        "SELECT DISTINCT f.libelle FROM famille f"
        " JOIN article_famille af ON af.famille_id = f.id"
        " JOIN production p ON p.article_code = af.article_code"
        " WHERE p.ligne_id = ? ORDER BY 1", (ligne_id,),
    ).fetchall()]

    colonnes = st.columns([1, 2])
    perimetre = colonnes[0].segmented_control(
        "Périmètre", ["ligne", "famille", "article"],
        default="ligne", key=f"{cle}_perimetre",
        format_func=lambda v: {"ligne": "Toute la ligne", "famille": "Une famille",
                               "article": "Un produit"}[v],
    ) or "ligne"

    if perimetre == "famille" and familles:
        choisie = colonnes[1].selectbox("Famille", familles, key=f"{cle}_famille")
        return None, choisie, f"famille {choisie}"
    if perimetre == "article" and articles:
        # Options déjà formatées plutôt qu'un format_func : le code reste lisible
        # dans le libellé, et la valeur du widget est directement inspectable.
        intitules = [f"{code} — {libelles_articles[code]}" for code in articles]
        choisi = colonnes[1].selectbox("Produit", intitules, key=f"{cle}_article")
        code = choisi.split(" — ", 1)[0] if choisi else articles[0]
        return code, None, f"produit {code}"
    return None, None, "toute la ligne"


def unite_ligne(ligne: dict) -> str:
    """Unité de comptage lue dans le libellé de la ligne (« ... (kg) »).

    Le modèle ne porte pas encore d'unité par ligne : tant qu'elle n'y est pas,
    on la lit là où l'utilisateur l'a écrite plutôt que de supposer l'UVC.
    """
    libelle = ligne.get("libelle", "")
    if "(" in libelle and ")" in libelle:
        candidat = libelle.rsplit("(", 1)[1].split(")")[0].strip()
        if candidat and len(candidat) <= 6:
            return candidat
    return "UVC"


def production_absente(conn: sqlite3.Connection, ligne_id: int) -> bool:
    """Vrai si la ligne n'a aucune production importée — message déjà affiché."""
    return conn.execute(
        "SELECT MAX(date) FROM production WHERE ligne_id = ?", (ligne_id,)
    ).fetchone()[0] is None


def exiger_ligne(conn: sqlite3.Connection) -> dict:
    """Récupère la ligne à analyser, ou explique comment démarrer."""
    ligne = ligne_active(conn)
    if ligne is None:
        st.info(
            "Aucune ligne de production n'est encore déclarée. Créez-la depuis la "
            "page Référentiel, avec ses cadences et son calendrier. Pour essayer "
            "l'application sans données réelles : `python generer_donnees_test.py`."
        )
        st.stop()
    return ligne


def bandeau_fraicheur(conn: sqlite3.Connection, ligne_id: int) -> str | None:
    """Affiche la date des données et alerte au-delà de 7 jours (CDC §6.7).

    Retourne la date de production la plus récente, ou None s'il n'y en a aucune.
    """
    derniere = conn.execute(
        "SELECT MAX(date) FROM production WHERE ligne_id = ?", (ligne_id,)
    ).fetchone()[0]
    dernier_import = conn.execute("SELECT MAX(date_import) FROM import_log").fetchone()[0]
    if derniere is None:
        st.warning(
            "Aucune donnée de production importée pour cette ligne. "
            "Rendez-vous sur la page Import."
        )
        return None
    retard = (date.today() - date.fromisoformat(derniere)).days
    fraicheur = f"Données à jour au {date.fromisoformat(derniere):%d/%m/%Y}"
    if dernier_import:
        fraicheur += f" · dernier import le {dernier_import[:10]}"
    if retard > 7:
        st.warning(
            f"{fraicheur}. Ces données datent de {retard} jours : une extraction "
            "plus récente est peut-être disponible."
        )
    else:
        st.caption(fraicheur)
    return derniere


def valider_periode(debut, fin) -> None:
    """Refuse une période impossible avant tout calcul."""
    if debut is None or fin is None:
        signaler("Renseignez une date de début et une date de fin.")
    if fin < debut:
        signaler(
            f"La fin de période ({fin:%d/%m/%Y}) est antérieure à son début "
            f"({debut:%d/%m/%Y}). Inversez les deux dates."
        )


def mention_niveau(resultat: dict) -> None:
    """Rappelle en permanence ce qui est mesuré et ce qui ne l'est pas (CDC §5.0)."""
    niveaux = {
        1: "Niveau 1 — TRS, TRG et TRE exacts. DO, TP et TQ non décomposés : "
           "aucun arrêt saisi, pas de compteur d'ensacheuse.",
        2: "Niveau 2 — arrêts saisis : DO et TP mesurés. TQ non mesuré : "
           "l'écart de cadence et la non-qualité restent regroupés.",
        3: "Niveau 3 — arrêts saisis et compteur d'ensacheuse : "
           "la cascade est entièrement décomposée.",
    }
    st.caption(niveaux[resultat["niveau_donnees"]])
