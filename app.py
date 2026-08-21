"""Page d'accueil : tableau de bord de synthèse (CDC §7.1).

Toute la logique vit dans core/ ; cette page ne fait qu'afficher.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import agregation, cadences, indicateurs, temps
from core.erreurs import ErreurMetier
from ui import commun, graphiques, theme

st.set_page_config(page_title="Rendement et TRS", layout="wide")
st.title("Rendement et TRS de la ligne")

conn = commun.ouvrir()
ligne = commun.exiger_ligne(conn)
derniere_production = commun.bandeau_fraicheur(conn, ligne["id"])
if derniere_production is None:
    st.stop()

# ---------------------------------------------------------------- période analysée

col_debut, col_fin = st.columns(2)
defaut_fin = date.fromisoformat(derniere_production)
defaut_debut = defaut_fin - timedelta(days=29)
periode_debut = col_debut.date_input("Début de période", value=defaut_debut)
periode_fin = col_fin.date_input("Fin de période", value=defaut_fin)
commun.valider_periode(periode_debut, periode_fin)

try:
    df = temps.cascade_journaliere(conn, ligne["id"], periode_debut, periode_fin)
    resultat = indicateurs.indicateurs_periode(df)
    par_semaine = agregation.agreger_par_periode(df, "semaine")
    changements = cadences.dates_changement(conn, ligne["id"], periode_debut, periode_fin)
except ErreurMetier as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        "Le calcul des indicateurs de la période a échoué. Vérifiez le référentiel "
        "— cadences et calendrier — depuis la page Référentiel, puis réessayez.",
        erreur,
    )

# ---------------------------------------------------------------- bandeau de capacité

st.subheader("Capacité et réalisation")
st.caption(
    "Le chiffre le plus simple à vérifier : ce que la ligne a produit, comparé à "
    "ce qu'elle aurait pu produire pendant le temps où elle devait tourner."
)
cadence_courante = cadences.cadence_la_plus_recente(conn, ligne["id"])
produisible = df[df["etat"] == temps.ETAT_OK]["qte_produisible_tr"].dropna().sum()

cartes = st.columns(4)
cartes[0].metric("Quantité produite",
                 theme.format_nombre(resultat["qte_produite"]) + " paquets")
cartes[1].metric("Quantité produisible sur le temps requis",
                 theme.format_nombre(produisible) + " paquets" if produisible
                 else "n/a")
if produisible:
    ecart = resultat["qte_produite"] - produisible
    cartes[2].metric("Écart à la capacité",
                     theme.format_nombre(ecart) + " paquets",
                     delta=theme.format_taux(ecart / produisible))
cartes[3].metric("Temps requis cumulé", theme.format_duree(resultat["Tr"]))

# ---------------------------------------------------------------- indicateurs

st.subheader("Indicateurs de la période")
cartes = st.columns(4)
cartes[0].metric("TRS", theme.format_taux(resultat["TRS"]))
cartes[1].metric("TRG", theme.format_taux(resultat["TRG"]),
                 help="Rapporte la production au temps d'ouverture : il intègre "
                      "donc le niveau de charge.")
cartes[2].metric("TRE", theme.format_taux(resultat["TRE"]))
cartes[3].metric("Taux de réalisation du plan",
                 theme.format_taux(resultat["taux_realisation"]))

cartes = st.columns(4)
cartes[0].metric("Disponibilité DO", theme.format_taux(resultat["DO"]))
cartes[1].metric("Performance TP", theme.format_taux(resultat["TP"]))
cartes[2].metric("Qualité TQ", theme.format_taux(resultat["TQ"]))
cartes[3].metric("Taux de charge TC", theme.format_taux(resultat["TC"]))

commun.mention_niveau(resultat)

if resultat["niveau_donnees"] < 3:
    manquant = []
    if not resultat["arrets_saisis"]:
        manquant.append(
            "la saisie des arrêts, avec horodatage de début et de fin, pour séparer "
            "la disponibilité de la performance"
        )
    if not resultat["qualite_mesuree"]:
        manquant.append(
            "un compteur en sortie d'ensacheuse, pour distinguer la non-qualité "
            "de l'écart de cadence"
        )
    st.info("Pour aller plus loin, il faudrait collecter : " + " ; ".join(manquant) + ".")

for alerte in resultat["alertes"]:
    st.warning(alerte)

# ---------------------------------------------------------------- évolution

st.subheader("Évolution du TRS par semaine")
if par_semaine.empty or par_semaine["TRS"].dropna().empty:
    st.info("Aucune semaine complète à afficher sur cet intervalle.")
else:
    graphique, tableau = st.tabs(["Graphique", "Tableau"])
    with graphique:
        st.plotly_chart(graphiques.evolution_trs(par_semaine, changements),
                        width="stretch")
    with tableau:
        lisible = par_semaine[["periode", "TRS", "TRG", "TRE"]].copy()
        for colonne in ("TRS", "TRG", "TRE"):
            lisible[colonne] = lisible[colonne].map(theme.format_taux)
        st.dataframe(lisible.rename(columns={"periode": "Semaine"}),
                     width="stretch", hide_index=True)

if changements:
    st.caption(
        "Repère vertical : la cadence de référence a changé le "
        + ", le ".join(f"{date.fromisoformat(d):%d/%m/%Y}" for d in changements)
        + ". Les valeurs de part et d'autre ne se comparent pas directement."
    )

# ---------------------------------------------------------------- jours manquants

jours_manquants = temps.jours_donnees_manquantes(df)
if jours_manquants:
    st.subheader("Jours sans données")
    st.warning(
        f"{len(jours_manquants)} jour(s) de la période devaient produire mais "
        "n'ont aucune ligne importée. Ils sont exclus des moyennes : un import "
        "oublié n'est pas une contre-performance."
    )
    st.dataframe(
        [{"Jour": f"{j:%d/%m/%Y}"} for j in jours_manquants],
        width="stretch", hide_index=True,
    )

conn.close()
