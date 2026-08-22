"""Écran d'analyse du TRS : cascade, taux, pertes, Pareto, comparaison (CDC §7.5).

Affichage seul : tout le calcul vit dans core/.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import agregation, arrets, cadences, indicateurs, temps
from core.erreurs import ErreurMetier
from ui import cartes, commun, graphiques, periode as periode_ui, theme


conn = commun.ouvrir()
lignes = commun.lignes_disponibles(conn)
if not lignes:
    commun.message_base_vide()

entete = st.columns([3, 2])
with entete[0]:
    st.title("TRS")
with entete[1]:
    ligne = commun.selecteur_ligne(conn, lignes, cle="trs")

commun.bandeau_fraicheur(conn, ligne["id"])
if commun.production_absente(conn, ligne["id"]):
    st.stop()

periode = periode_ui.selecteur(conn, ligne["id"])
periode_debut, periode_fin, maille = periode.debut, periode.fin, periode.maille
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

if changements:
    st.warning(
        "La cadence de référence change le "
        + ", le ".join(f"{date.fromisoformat(d):%d/%m/%Y}" for d in changements)
        + " sur la période analysée. Un TRS plus bas après cette date peut venir "
        "d'une référence plus haute, pas d'une performance dégradée. "
        "Utilisez la comparaison à cadence constante, en bas de page."
    )

# ---------------------------------------------------------------- indicateurs

cartes.indicateur_principal(resultat, unite=commun.unite_ligne(ligne))
cartes.bandeau_niveau(resultat)
st.caption(
    f"Temps requis : mode {mode}."
    + ("  Les arrêts hors requis sont affichés mais non retranchés."
       if mode == "FIXE" else
       "  Le temps requis est déduit des arrêts hors requis déclarés.")
)

colonnes = st.columns([2, 1])
with colonnes[0]:
    cartes.cartes_cascade(resultat)
with colonnes[1]:
    st.markdown("**Réalisation du plan**")
    st.metric("Taux de réalisation", theme.format_taux(resultat["taux_realisation"]))

with st.expander("Autres indicateurs de contexte"):
    cartes.cartes_contexte(resultat)

cartes.alertes(resultat, limite=3)

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

st.subheader(f"Évolution par {periode_ui.LIBELLES_MAILLE[maille].lower()}")
if par_periode.empty or par_periode["TRS"].dropna().empty:
    st.info("Aucune période complète à afficher sur cet intervalle.")
else:
    graphique, tableau = st.tabs(["Graphique", "Tableau"])
    with graphique:
        st.plotly_chart(
            graphiques.evolution_trs(par_periode, changements, maille=maille),
            width="stretch")
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
    niveau = st.segmented_control(
        "Lecture", ["motif", "zone", "element"], default="motif",
        format_func=lambda v: {"motif": "Par motif", "zone": "Par zone",
                               "element": "Par équipement"}[v],
    ) or "motif"
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
duree = periode.nb_jours
precedente_fin = periode_debut - timedelta(days=1)
precedente_debut = precedente_fin - timedelta(days=duree - 1)

colonnes = st.columns(4)
a_debut = colonnes[0].date_input("Période A — début", value=precedente_debut,
                                 key="a_debut", format="DD/MM/YYYY")
a_fin = colonnes[1].date_input("Période A — fin", value=precedente_fin,
                               key="a_fin", format="DD/MM/YYYY")
b_debut = colonnes[2].date_input("Période B — début", value=periode_debut,
                                 key="b_debut", format="DD/MM/YYYY")
b_fin = colonnes[3].date_input("Période B — fin", value=periode_fin,
                               key="b_fin", format="DD/MM/YYYY")
st.caption(
    f"Par défaut : la période analysée ({duree} jours) comparée aux {duree} jours "
    "qui la précèdent."
)

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
