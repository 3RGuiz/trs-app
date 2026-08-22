"""Tableau de bord d'accueil (CDC §7.1).

Ordre de lecture voulu : d'abord le chiffre qui répond à « où on en est »,
ensuite sa décomposition, enfin ce qui mérite attention. Toute la logique vit
dans core/ ; cette page ne fait qu'afficher.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from core import agregation, cadences, indicateurs, temps
from core.erreurs import ErreurMetier
from ui import cartes, commun, graphiques, periode as periode_ui, theme

st.set_page_config(page_title="Rendement et TRS", layout="wide")

conn = commun.ouvrir()
lignes = commun.lignes_disponibles(conn)
if not lignes:
    commun.message_base_vide()

# ---------------------------------------------------------------- en-tête

entete = st.columns([3, 2])
with entete[0]:
    st.title("Rendement et TRS")
with entete[1]:
    ligne = commun.selecteur_ligne(conn, lignes, cle="accueil")

commun.bandeau_fraicheur(conn, ligne["id"])
if commun.production_absente(conn, ligne["id"]):
    st.stop()

periode = periode_ui.selecteur(conn, ligne["id"])
commun.valider_periode(periode.debut, periode.fin)

try:
    cascade = temps.cascade_journaliere(conn, ligne["id"], periode.debut, periode.fin)
    resultat = indicateurs.indicateurs_periode(cascade)
    par_maille = agregation.agreger_par_periode(cascade, periode.maille)
    changements = cadences.dates_changement(conn, ligne["id"], periode.debut, periode.fin)
except ErreurMetier as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        "Le calcul des indicateurs a échoué. Vérifiez les cadences et le "
        "calendrier depuis la page Référentiel, puis réessayez.", erreur,
    )

# ---------------------------------------------------------------- synthèse

cartes.indicateur_principal(resultat, unite=commun.unite_ligne(ligne))
cartes.bandeau_niveau(resultat)

colonnes = st.columns([2, 1])
with colonnes[0]:
    cartes.cartes_cascade(resultat)
with colonnes[1]:
    st.markdown("**Réalisation du plan**")
    st.metric("Taux de réalisation", theme.format_taux(resultat["taux_realisation"]),
              help=cartes.DEFINITIONS["taux_realisation"])
    st.caption(
        f"{theme.format_nombre(resultat['qte_produite'])} produites pour "
        f"{theme.format_nombre(resultat['qte_planifiee'])} planifiées."
    )

with st.expander("Autres indicateurs de contexte"):
    cartes.cartes_contexte(resultat)
    st.caption(
        "Le TRG intègre le niveau de charge : il baisse quand la ligne est peu "
        "chargée, même si elle tourne bien pendant qu'elle produit."
    )

# ---------------------------------------------------------------- évolution

st.subheader(f"Évolution par {periode_ui.LIBELLES_MAILLE[periode.maille].lower()}")
if par_maille.empty or par_maille["TRS"].dropna().empty:
    st.info(
        "Aucune période complète à afficher. Élargissez l'intervalle, ou "
        "choisissez une maille plus fine."
    )
else:
    graphique, tableau = st.tabs(["Graphique", "Tableau"])
    with graphique:
        st.plotly_chart(
            graphiques.evolution_trs(par_maille, changements, maille=periode.maille),
            width="stretch")
        if changements:
            st.caption(
                "Repère vertical : changement de la cadence de référence le "
                + ", le ".join(f"{date.fromisoformat(d):%d/%m/%Y}" for d in changements)
                + ". Les valeurs de part et d'autre ne se comparent pas directement."
            )
    with tableau:
        lisible = par_maille[["periode", "TRS", "TRG", "TRE", "qte_produite"]].copy()
        for colonne in ("TRS", "TRG", "TRE"):
            lisible[colonne] = lisible[colonne].map(theme.format_taux)
        lisible["qte_produite"] = lisible["qte_produite"].map(theme.format_nombre)
        st.dataframe(
            lisible.rename(columns={"periode": "Période", "qte_produite": "Produit"}),
            width="stretch", hide_index=True,
        )

# ---------------------------------------------------------------- points d'attention

st.subheader("Points d'attention")
cartes.alertes(resultat, limite=3)

jours_manquants = temps.jours_donnees_manquantes(cascade)
if jours_manquants:
    with st.expander(f"{len(jours_manquants)} jour(s) requis sans données importées"):
        st.write(
            "Ces journées devaient produire mais n'ont aucune ligne importée. "
            "Elles sont exclues des moyennes : un import oublié n'est pas une "
            "contre-performance."
        )
        st.dataframe([{"Jour": f"{j:%d/%m/%Y}"} for j in jours_manquants],
                     width="stretch", hide_index=True)

if not resultat.get("alertes") and not jours_manquants:
    st.caption("Rien à signaler sur cette période.")

conn.close()
