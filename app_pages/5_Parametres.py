"""Paramètres, sauvegarde et restauration (CDC §7.6, §13.7).

La base de travail ne vit jamais dans un dossier synchronisé : seules des copies
propres, produites par VACUUM INTO, y sont écrites. Une sauvegarde qui échoue en
silence est pire que pas de sauvegarde — la date de la dernière réussite est donc
affichée en permanence.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import sauvegarde
from core.erreurs import SauvegardeEchouee
from ui import commun, theme

st.title("Paramètres")

conn = commun.ouvrir()
chemin_db = commun.chemin_base()


def parametre(cle: str, defaut: str = "") -> str:
    ligne = conn.execute("SELECT valeur FROM parametre WHERE cle = ?", (cle,)).fetchone()
    return ligne["valeur"] if ligne else defaut


def enregistrer_parametre(cle: str, valeur: str) -> None:
    conn.execute(
        "INSERT INTO parametre (cle, valeur) VALUES (?, ?)"
        " ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (cle, valeur),
    )
    conn.commit()


# ---------------------------------------------------------------- base de données

st.subheader("Base de données")
taille = chemin_db.stat().st_size / 1024 if chemin_db.exists() else 0
colonnes = st.columns(3)
colonnes[0].metric("Lignes de production",
                   theme.format_nombre(
                       conn.execute("SELECT COUNT(*) FROM production").fetchone()[0]))
colonnes[1].metric("Arrêts saisis",
                   theme.format_nombre(
                       conn.execute("SELECT COUNT(*) FROM arret").fetchone()[0]))
colonnes[2].metric("Taille du fichier", f"{theme.format_nombre(taille)} Ko")
st.caption(f"Emplacement : {chemin_db}")

# ---------------------------------------------------------------- sauvegarde

st.subheader("Sauvegarde")
st.caption(
    "Les copies partent vers un dossier de votre choix — typiquement le dossier "
    "SharePoint synchronisé. La base de travail, elle, reste toujours en local : "
    "un client de synchronisation peut corrompre un fichier copié pendant une écriture."
)

destination = st.text_input(
    "Dossier de destination des sauvegardes",
    value=parametre("chemin_sauvegarde", str(chemin_db.parent / "sauvegardes")),
)
colonnes = st.columns(2)
retention_jours = colonnes[0].number_input(
    "Sauvegardes quotidiennes conservées", value=int(parametre("retention_jours", "30")),
    min_value=1, max_value=365,
)
retention_mois = colonnes[1].number_input(
    "Sauvegardes mensuelles conservées", value=int(parametre("retention_mois", "12")),
    min_value=1, max_value=120,
    help="La copie du 1er de chaque mois n'est jamais purgée par la rétention quotidienne.",
)

dossier = Path(destination) if destination.strip() else None
if dossier:
    derniere = sauvegarde.derniere_reussite(dossier / sauvegarde.NOM_JOURNAL)
    if derniere is None:
        st.warning(
            "Aucune sauvegarde réussie enregistrée pour ce dossier. "
            "Lancez-en une dès maintenant."
        )
    else:
        age = (datetime.now() - derniere).days
        message = f"Dernière sauvegarde réussie le {derniere:%d/%m/%Y à %H h %M}."
        if age > 3:
            st.warning(message + f" Elle date de {age} jours.")
        else:
            st.success(message)

colonnes = st.columns(2)
if colonnes[0].button("Sauvegarder maintenant", type="primary"):
    if not dossier:
        st.error("Indiquez d'abord un dossier de destination.")
    else:
        enregistrer_parametre("chemin_sauvegarde", str(dossier))
        enregistrer_parametre("retention_jours", str(int(retention_jours)))
        enregistrer_parametre("retention_mois", str(int(retention_mois)))
        conn.commit()
        try:
            cible = sauvegarde.sauvegarder(chemin_db, dossier)
        except SauvegardeEchouee as erreur:
            st.error(str(erreur))
        except Exception as erreur:
            commun.signaler(
                f"La sauvegarde vers {dossier} a échoué. Vérifiez que le dossier "
                "existe et qu'il est accessible en écriture.", erreur,
            )
        else:
            supprimes = sauvegarde.rotation(
                dossier, retention_jours=int(retention_jours),
                retention_mois=int(retention_mois),
            )
            st.success(
                f"Sauvegarde écrite et vérifiée : {cible.name}"
                + (f" — {len(supprimes)} ancienne(s) copie(s) purgée(s)."
                   if supprimes else ".")
            )

if colonnes[1].button("Enregistrer les réglages"):
    enregistrer_parametre("chemin_sauvegarde", str(destination))
    enregistrer_parametre("retention_jours", str(int(retention_jours)))
    enregistrer_parametre("retention_mois", str(int(retention_mois)))
    st.success("Réglages enregistrés.")

if dossier and dossier.exists():
    copies = sorted(dossier.glob("trs_*.db"), reverse=True)[:15]
    if copies:
        st.dataframe(
            [{
                "Fichier": c.name,
                "Écrite le": datetime.fromtimestamp(c.stat().st_mtime).strftime(
                    "%d/%m/%Y %H:%M"),
                "Taille": f"{theme.format_nombre(c.stat().st_size / 1024)} Ko",
            } for c in copies],
            width="stretch", hide_index=True,
        )

# ---------------------------------------------------------------- restauration

st.subheader("Restaurer une sauvegarde")
st.warning(
    "La restauration remplace la base actuelle. Elle se fait application fermée, "
    "en trois étapes : fermer l'application, copier le fichier daté depuis le "
    "dossier de sauvegarde vers le dossier data, le renommer trs.db, puis relancer."
)

st.subheader("Fraîcheur et seuils")
seuil = st.number_input(
    "Alerter quand les données datent de plus de (jours)",
    value=int(parametre("seuil_fraicheur_jours", "7")), min_value=1, max_value=90,
)
if st.button("Enregistrer le seuil"):
    enregistrer_parametre("seuil_fraicheur_jours", str(int(seuil)))
    st.success("Seuil enregistré.")

st.caption(
    "Les paramètres qui entrent dans le calcul — mode de calcul du temps requis, "
    "début d'historique exploitable — sont datés et se modifient depuis la page "
    "Référentiel, onglet « Paramètres de calcul »."
)

conn.close()
