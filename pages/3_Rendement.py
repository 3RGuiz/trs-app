"""Taux de réalisation par article et par famille (CDC §7.4).

Rappel de la limite du modèle : le TRS ne se décline pas par article. Tu se
ventile bien par article, Tr non — l'ERP ne donne pas les horaires d'ordre de
fabrication. Cet écran expose donc le taux de réalisation, la quantité produite
et le temps théorique consommé, jamais un TRS par article.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import agregation
from core.erreurs import ErreurMetier
from ui import commun, periode as periode_ui, theme

st.set_page_config(page_title="Rendement", layout="wide")

conn = commun.ouvrir()
lignes = commun.lignes_disponibles(conn)
if not lignes:
    commun.message_base_vide()

entete = st.columns([3, 2])
with entete[0]:
    st.title("Rendement")
with entete[1]:
    ligne = commun.selecteur_ligne(conn, lignes, cle="rendement")

commun.bandeau_fraicheur(conn, ligne["id"])
if commun.production_absente(conn, ligne["id"]):
    st.stop()

periode = periode_ui.selecteur(conn, ligne["id"], avec_maille=False)
periode_debut, periode_fin = periode.debut, periode.fin
vue = st.segmented_control(
    "Lecture des familles", ["historique", "actuelle"], default="historique",
    format_func=lambda v: "Familles de l'époque" if v == "historique"
    else "Catalogue d'aujourd'hui",
) or "historique"
commun.valider_periode(periode_debut, periode_fin)

st.caption(
    "Familles de l'époque : chaque production est comptée dans la famille en "
    "vigueur à sa date, le passé ne bouge pas. Catalogue d'aujourd'hui : tout "
    "l'historique est recompté avec le rattachement actuel."
    if vue == "historique" else
    "Lecture « catalogue d'aujourd'hui » : l'historique est recompté avec les "
    "rattachements actuels, ce qui modifie la répartition passée entre familles."
)

try:
    par_article = agregation.par_article(conn, ligne["id"], periode_debut, periode_fin)
    par_famille = agregation.par_famille(conn, ligne["id"], periode_debut, periode_fin,
                                         vue=vue)
except ErreurMetier as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        "Le calcul du rendement a échoué. Vérifiez que les cadences couvrent la "
        "période analysée, depuis la page Référentiel.", erreur,
    )


def mettre_en_forme(df, colonne_cle: str, libelle_cle: str):
    if df.empty:
        return []
    lisible = df.copy()
    lisible = lisible.sort_values("taux_realisation", na_position="last")
    return [
        {
            libelle_cle: ligne_df[colonne_cle],
            "Quantité planifiée": theme.format_nombre(ligne_df["qte_planifiee"]),
            "Quantité produite": theme.format_nombre(ligne_df["qte_produite"]),
            "Taux de réalisation": theme.format_taux(ligne_df["taux_realisation"]),
            "Temps théorique consommé": theme.format_duree(
                ligne_df["temps_theorique_min"]),
        }
        for _, ligne_df in lisible.iterrows()
    ]


st.subheader("Par article")
if par_article.empty:
    st.info("Aucune production exploitable sur la période.")
else:
    st.dataframe(mettre_en_forme(par_article, "article_code", "Article"),
                 width="stretch", hide_index=True)
    st.caption(
        "Trié par écart au plan, du plus faible au plus élevé. Le temps théorique "
        "consommé indique quelle part de la capacité chaque article a mobilisée."
    )

st.subheader("Par famille")
if par_famille.empty:
    st.info("Aucune production exploitable sur la période.")
else:
    st.dataframe(mettre_en_forme(par_famille, "famille", "Famille"),
                 width="stretch", hide_index=True)

st.info(
    "Le TRS, le TRG et le TRE ne sont pas déclinés par article : l'ERP ne donne "
    "pas le temps passé sur chaque ordre de fabrication, et toute répartition "
    "inventée du temps requis redonnerait le taux de réalisation sous un autre "
    "nom. Ces indicateurs restent au niveau de la ligne, sur la page TRS."
)

conn.close()
