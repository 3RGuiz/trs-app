"""Écran d'analyse du TRS : cascade, taux, pertes, Pareto, comparaison (CDC §7.5).

Affichage seul : tout le calcul vit dans core/.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import agregation, arrets, cadences, indicateurs, temps
from core.erreurs import ErreurMetier
from ui import commun, graphiques, theme

st.set_page_config(page_title="TRS", layout="wide")
st.title("TRS de la ligne")

conn = commun.ouvrir()
ligne = commun.exiger_ligne(conn)
derniere = commun.bandeau_fraicheur(conn, ligne["id"])
if derniere is None:
    st.stop()

# ---------------------------------------------------------------- période

colonnes = st.columns([1, 1, 1])
defaut_fin = date.fromisoformat(derniere)
defaut_debut = defaut_fin - timedelta(days=29)
periode_debut = colonnes[0].date_input("Début de période", value=defaut_debut)
periode_fin = colonnes[1].date_input("Fin de période", value=defaut_fin)
maille = colonnes[2].selectbox("Maille d'analyse", ["jour", "semaine", "mois", "annee"],
                               index=1)
commun.valider_periode(periode_debut, periode_fin)

try:
    cascade = temps.cascade_journaliere(conn, ligne["id"], periode_debut, periode_fin)
    resultat = indicateurs.indicateurs_periode(cascade)
    par_periode = agregation.agreger_par_periode(cascade, maille)
    changements = cadences.dates_changement(conn, ligne["id"], periode_debut, periode_fin)
except ErreurMetier as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        "Le calcul du TRS a échoué. Vérifiez les cadences et le calendrier depuis "
        "la page Référentiel, puis réessayez.", erreur,
    )

mode = temps.mode_tr(conn, periode_fin)
st.caption(f"Mode de calcul du temps requis : {mode}")
commun.mention_niveau(resultat)

if changements:
    st.warning(
        "La cadence de référence change le "
        + ", le ".join(f"{date.fromisoformat(d):%d/%m/%Y}" for d in changements)
        + " sur la période analysée. Un TRS plus bas après cette date peut venir "
        "d'une référence plus haute, pas d'une performance dégradée. "
        "Utilisez la comparaison à cadence constante, en bas de page."
    )

# ---------------------------------------------------------------- indicateurs

st.subheader("Indicateurs de la période")
cartes = st.columns(4)
cartes[0].metric("TRS", theme.format_taux(resultat["TRS"]))
cartes[1].metric("TRG", theme.format_taux(resultat["TRG"]),
                 help="Rapporte la production au temps d'ouverture : il intègre "
                      "donc le niveau de charge.")
cartes[2].metric("TRE", theme.format_taux(resultat["TRE"]))
cartes[3].metric("Taux de réalisation", theme.format_taux(resultat["taux_realisation"]))

cartes = st.columns(5)
cartes[0].metric("Qualité TQ", theme.format_taux(resultat["TQ"]))
cartes[1].metric("Performance TP", theme.format_taux(resultat["TP"]))
cartes[2].metric("Disponibilité DO", theme.format_taux(resultat["DO"]))
cartes[3].metric("Charge TC", theme.format_taux(resultat["TC"]))
cartes[4].metric("Stratégique TS", theme.format_taux(resultat["TS"]))

for alerte in resultat["alertes"]:
    st.warning(alerte)

# ---------------------------------------------------------------- cascade

st.subheader("Cascade des temps")
graphique, tableau = st.tabs(["Graphique", "Tableau"])
with graphique:
    st.plotly_chart(graphiques.cascade_des_temps(resultat), width="stretch")
with tableau:
    st.dataframe(
        {
            "Temps": [graphiques.LIBELLES_TEMPS[n] for n in graphiques.ORDRE_CASCADE],
            "Durée": [theme.format_duree(resultat[n]) for n in graphiques.ORDRE_CASCADE],
            "Minutes": [round(resultat[n], 1) for n in graphiques.ORDRE_CASCADE],
        },
        width="stretch", hide_index=True,
    )

st.subheader("Où passe le temps")
graphique, tableau = st.tabs(["Graphique", "Tableau"])
with graphique:
    st.plotly_chart(graphiques.pertes_par_etage(resultat), width="stretch")
with tableau:
    pertes = []
    for amont, aval, libelle in (
        ("Tt", "To", "Hors ouverture"), ("To", "Tr", "Hors requis"),
        ("Tr", "Tf", "Arrêts propres"), ("Tf", "Tn", "Écart de cadence"),
        ("Tn", "Tu", "Non-qualité"),
    ):
        pertes.append({"Poste": libelle,
                       "Minutes perdues": round(resultat[amont] - resultat[aval], 1)})
    st.dataframe(pertes, width="stretch", hide_index=True)

# ---------------------------------------------------------------- évolution

st.subheader(f"Évolution du TRS par {maille}")
if par_periode.empty or par_periode["TRS"].dropna().empty:
    st.info("Aucune période complète à afficher sur cet intervalle.")
else:
    graphique, tableau = st.tabs(["Graphique", "Tableau"])
    with graphique:
        st.plotly_chart(
            graphiques.evolution_trs(par_periode, changements), width="stretch"
        )
    with tableau:
        lisible = par_periode[["periode", "TRS", "TRG", "TRE", "Tu", "Tr", "To"]].copy()
        for colonne in ("TRS", "TRG", "TRE"):
            lisible[colonne] = lisible[colonne].map(theme.format_taux)
        for colonne in ("Tu", "Tr", "To"):
            lisible[colonne] = lisible[colonne].map(theme.format_duree)
        st.dataframe(lisible, width="stretch", hide_index=True)

# ---------------------------------------------------------------- Pareto

st.subheader("Origine des arrêts")
if resultat["nb_arrets_saisis"] == 0:
    st.info(
        "Aucun arrêt saisi sur la période : le TRS reste exact, mais sa "
        "décomposition entre disponibilité et performance n'est pas mesurable. "
        "La saisie se fait depuis la page Arrêts."
    )
else:
    niveau = st.radio("Lecture", ["motif", "zone", "element"], horizontal=True,
                      format_func=lambda v: {"motif": "Par motif", "zone": "Par zone",
                                             "element": "Par équipement"}[v])
    try:
        pareto = arrets.pareto(conn, ligne["id"], periode_debut, periode_fin, par=niveau)
    except Exception as erreur:
        commun.signaler("Le Pareto des arrêts n'a pas pu être calculé.", erreur)
    if pareto.empty:
        st.info("Aucun arrêt sur la période.")
    else:
        graphique, tableau = st.tabs(["Graphique", "Tableau"])
        with graphique:
            st.plotly_chart(graphiques.pareto_arrets(pareto), width="stretch")
        with tableau:
            lisible = pareto.copy()
            lisible["Durée"] = lisible["duree_min"].map(theme.format_duree)
            lisible = lisible.rename(columns={"libelle": "Origine",
                                              "nb_arrets": "Nombre d'arrêts"})
            st.dataframe(lisible[["Origine", "Durée", "Nombre d'arrêts"]],
                         width="stretch", hide_index=True)
        st.caption(
            "Le Pareto compte tous les arrêts déclarés, y compris ceux absorbés "
            "par un tampon qui n'ont pas arrêté la ligne : ils n'entrent pas dans "
            "la cascade mais restent utiles pour chercher les causes."
        )

# ---------------------------------------------------------------- comparaison

st.subheader("Comparer deux périodes")
st.caption(
    "Quand la cadence de référence a changé entre les deux périodes, la lecture "
    "à cadence constante recalcule les deux avec la même référence : c'est elle "
    "qui montre le progrès réel."
)
colonnes = st.columns(4)
a_debut = colonnes[0].date_input("Période A — début", value=defaut_debut - timedelta(days=30),
                                 key="a_debut")
a_fin = colonnes[1].date_input("Période A — fin", value=defaut_debut - timedelta(days=1),
                               key="a_fin")
b_debut = colonnes[2].date_input("Période B — début", value=defaut_debut, key="b_debut")
b_fin = colonnes[3].date_input("Période B — fin", value=defaut_fin, key="b_fin")

if st.button("Comparer"):
    commun.valider_periode(a_debut, a_fin)
    commun.valider_periode(b_debut, b_fin)
    try:
        comparaison = agregation.comparer_periodes(
            conn, ligne["id"], (a_debut, a_fin), (b_debut, b_fin)
        )
    except ErreurMetier as erreur:
        commun.signaler(str(erreur), erreur)
    except Exception as erreur:
        commun.signaler("La comparaison des deux périodes a échoué.", erreur)

    if comparaison["avertissement"]:
        st.warning(comparaison["avertissement"])

    lignes = []
    for cle, libelle in (("reelle", "Cadence en vigueur à chaque date"),
                         ("constante", f"À cadence constante "
                                       f"({theme.format_nombre(comparaison['cadence_constante'])} ppm)")):
        lecture = comparaison[cle]
        if lecture is None:
            continue
        ecart = lecture["ecart_trs"]
        lignes.append({
            "Lecture": libelle,
            "TRS période A": theme.format_taux(lecture["a"]["TRS"]),
            "TRS période B": theme.format_taux(lecture["b"]["TRS"]),
            "Écart": "n/a" if ecart is None
                     else f"{'+' if ecart >= 0 else '−'}{theme.format_nombre(abs(ecart) * 100, 1)} pt",
        })
    st.dataframe(lignes, width="stretch", hide_index=True)

conn.close()
