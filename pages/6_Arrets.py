"""Saisie des arrêts (CDC §7.7).

Séquence : date et horaires, élément de la ligne, motif filtré sur cet élément,
la ligne s'est-elle arrêtée, commentaire. Un motif manquant se crée sans quitter
l'écran, avec recherche de libellés proches avant création.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from core import arrets, elements, motifs, temps
from core.erreurs import ErreurMetier
from ui import commun, theme

st.set_page_config(page_title="Arrêts", layout="wide")
st.title("Saisie des arrêts")

conn = commun.ouvrir()
ligne = commun.exiger_ligne(conn)

st.caption(
    "Les horodatages de début et de fin sont essentiels : sans eux, deux arrêts "
    "simultanés seraient comptés deux fois, et c'est irrattrapable après coup."
)

jour = st.date_input("Jour de production", value=date.today())
arbre = elements.elements_en_service(conn, ligne["id"], jour)

if not arbre:
    st.warning(
        "Aucun élément de ligne n'est en service à cette date. Déclarez la "
        "composition de la ligne depuis la page Référentiel."
    )

# ---------------------------------------------------------------- création de motif

with st.expander("Ajouter un motif au catalogue"):
    st.caption(
        "Un motif décrit une cause d'arrêt. Il ne doit jamais décrire une "
        "sous-cadence ou un bridage : cette perte est calculée par différence et "
        "apparaît dans le taux de performance ; la saisir en arrêt la compterait deux fois."
    )
    with st.form("motif_a_la_volee"):
        colonnes = st.columns(3)
        libelle_motif = colonnes[0].text_input("Libellé du motif")
        categorie = colonnes[1].selectbox(
            "Catégorie", ["ARRET_PROPRE", "HORS_REQUIS"],
            format_func=lambda v: "Arrêt propre — aléa subi" if v == "ARRET_PROPRE"
            else "Hors requis — pause, nettoyage, sous-charge",
            help="La quasi-totalité des motifs créés dans le feu de l'action sont "
                 "des aléas subis : arrêt propre.",
        )
        rattachement = colonnes[2].selectbox(
            "Rattacher à", [None] + [e["id"] for e in arbre],
            format_func=lambda v: "Motif global (proposé partout)" if v is None
            else next(e["libelle"] for e in arbre if e["id"] == v),
            key="rattachement_motif",
        )
        if st.form_submit_button("Créer le motif") and libelle_motif.strip():
            proches = motifs.libelles_proches(conn, libelle_motif)
            if proches:
                st.warning(
                    "Motifs déjà existants et très proches : "
                    + ", ".join(f"« {m['libelle']} »" for m in proches[:5])
                    + ". Utilisez l'un d'eux plutôt que de créer un doublon."
                )
            try:
                motifs.creer_motif(
                    conn, code=libelle_motif.strip().upper().replace(" ", "-")[:40],
                    libelle=libelle_motif.strip(), categorie=categorie,
                    date_debut=jour, commentaire="Créé depuis l'écran de saisie",
                    auteur="utilisateur", element_id=rattachement,
                )
            except ErreurMetier as erreur:
                st.error(str(erreur))
            else:
                st.success(f"Motif « {libelle_motif} » créé.")
                st.rerun()

# ---------------------------------------------------------------- saisie d'un arrêt

st.subheader("Déclarer un arrêt")
colonnes = st.columns(2)
element_choisi = colonnes[0].selectbox(
    "Élément à l'origine de l'arrêt", [None] + [e["id"] for e in arbre],
    format_func=lambda v: "Origine non renseignée" if v is None
    else next(e["libelle"] for e in arbre if e["id"] == v),
)
proposes = motifs.motifs_proposes(conn, element_choisi, jour)
if not proposes:
    st.warning("Aucun motif disponible à cette date. Créez-en un ci-dessus.")
    st.stop()
motif_choisi = colonnes[1].selectbox(
    "Motif", [m["id"] for m in proposes],
    format_func=lambda v: next(m["libelle"] for m in proposes if m["id"] == v),
)
st.caption(
    "La liste réunit les motifs de cet élément, ceux de ses zones parentes et "
    "les motifs globaux."
)

with st.form("saisie_arret"):
    colonnes = st.columns(4)
    heure_debut = colonnes[0].time_input("Début", value=time(8, 0))
    heure_fin = colonnes[1].time_input("Fin", value=time(8, 30))
    arrete_ligne = colonnes[2].selectbox(
        "La ligne s'est-elle arrêtée ?", [1, 0],
        format_func=lambda v: "Oui — la ligne a cessé de produire" if v
        else "Non — absorbé par un tampon",
    )
    lendemain = colonnes[3].checkbox(
        "La fin est le lendemain", help="Pour un arrêt à cheval sur minuit."
    )
    commentaire = st.text_input("Commentaire (facultatif)")

    if st.form_submit_button("Enregistrer l'arrêt", type="primary"):
        debut = datetime.combine(jour, heure_debut)
        fin = datetime.combine(jour + timedelta(days=1) if lendemain else jour, heure_fin)
        alerte = arrets.verifier_element_en_service(conn, element_choisi, jour)
        if alerte:
            st.warning(alerte + " L'arrêt est tout de même enregistré.")
        try:
            arrets.saisir_arret(
                conn, ligne["id"], jour, motif_choisi, debut=debut, fin=fin,
                element_id=element_choisi, arrete_ligne=int(arrete_ligne),
                commentaire=commentaire.strip() or None,
            )
        except ErreurMetier as erreur:
            st.error(str(erreur))
        except Exception as erreur:
            commun.signaler("L'arrêt n'a pas pu être enregistré.", erreur)
        else:
            st.success("Arrêt enregistré.")
            st.rerun()

# ---------------------------------------------------------------- récapitulatif

st.subheader(f"Arrêts du {jour:%d/%m/%Y}")
du_jour = arrets.arrets_du_jour(conn, ligne["id"], jour)
if not du_jour:
    st.info("Aucun arrêt déclaré ce jour.")
else:
    libelles = {
        m["id"]: m["libelle"]
        for m in conn.execute("SELECT id, libelle FROM motif_arret").fetchall()
    }
    noms_elements = {
        e["id"]: e["libelle"]
        for e in conn.execute("SELECT id, libelle FROM element_ligne").fetchall()
    }
    st.dataframe(
        [{
            "Début": (a["debut"] or "")[-8:-3] if a["debut"] else "non horodaté",
            "Fin": (a["fin"] or "")[-8:-3] if a["fin"] else "non horodaté",
            "Durée": theme.format_duree(a["duree_min"]),
            "Origine": noms_elements.get(a["element_id"], "Non renseignée"),
            "Motif": libelles.get(a["motif_id"], ""),
            "Catégorie": "Arrêt propre" if a["categorie"] == "ARRET_PROPRE"
                         else "Hors requis",
            "Ligne arrêtée": "Oui" if a["arrete_ligne"] else "Non (tampon)",
        } for a in du_jour],
        width="stretch", hide_index=True,
    )

    cumul = arrets.temps_arrets_jour(conn, ligne["id"], jour)
    to_min, tr_min = temps.calendrier_du_jour(conn, ligne["id"], jour)
    cartes = st.columns(3)
    cartes[0].metric("Arrêts propres (union)", theme.format_duree(cumul["ARRET_PROPRE"]))
    cartes[1].metric("Hors requis (union)", theme.format_duree(cumul["HORS_REQUIS"]))
    cartes[2].metric("Temps requis du jour", theme.format_duree(tr_min))
    st.caption(
        "Les durées sont calculées par union des intervalles : deux arrêts "
        "simultanés n'arrêtent la ligne qu'une fois. La somme brute des durées "
        f"déclarées vaut {theme.format_duree(sum(a['duree_min'] for a in du_jour))}."
    )
    if cumul["avertissement_horodatage"]:
        st.warning(
            "Certains arrêts n'ont pas d'horodatage : leurs durées sont "
            "additionnées sans détection des chevauchements possibles."
        )
    if temps.mode_tr(conn, jour) == "FIXE" and cumul["HORS_REQUIS"] > 0:
        st.info(
            "Le mode de calcul du temps requis est FIXE : les arrêts hors requis "
            "sont conservés pour l'analyse mais ne sont pas retranchés, sous peine "
            "de double comptage."
        )

conn.close()
