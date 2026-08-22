"""Référentiels historisés (CDC §7.3).

Tous les onglets partagent le composant ui/referentiel_widget.py : consultation
de la valeur en vigueur, frise de l'historique, formulaire de changement avec
date d'effet et commentaire obligatoire. Le passé ne se réécrit jamais.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import cadences, elements, historisation, motifs
from core.erreurs import ErreurMetier
from ui import commun, referentiel_widget, theme

st.title("Référentiel")

conn = commun.ouvrir()
ligne = commun.ligne_active(conn)

# ---------------------------------------------------------------- création de la ligne

if ligne is None:
    st.info(
        "Première utilisation : déclarez la ligne de production à mesurer. "
        "Vous pourrez ensuite saisir sa composition, ses cadences et son calendrier."
    )
    with st.form("creer_ligne"):
        code = st.text_input("Code de la ligne", placeholder="LIGNE-1")
        libelle = st.text_input("Libellé", placeholder="Ligne de conditionnement 1")
        mise_en_service = st.date_input("Date de mise en service", value=date.today())
        if st.form_submit_button("Créer la ligne"):
            if not code.strip() or not libelle.strip():
                st.error("Le code et le libellé de la ligne sont obligatoires.")
            else:
                try:
                    conn.execute(
                        "INSERT INTO ligne (code, libelle, date_debut) VALUES (?, ?, ?)",
                        (code.strip(), libelle.strip(), mise_en_service.isoformat()),
                    )
                    conn.commit()
                except Exception as erreur:
                    commun.signaler(
                        f"La ligne « {code} » n'a pas pu être créée : ce code est "
                        "peut-être déjà utilisé.", erreur,
                    )
                st.success("Ligne créée. Poursuivez avec les cadences et le calendrier.")
                st.rerun()
    st.stop()

st.caption(f"Ligne mesurée : {ligne['libelle']} ({ligne['code']})")

onglets = st.tabs([
    "Cadences", "Calendrier", "Articles et familles", "Motifs d'arrêt",
    "Composition de la ligne", "Paramètres de calcul", "Journal des modifications",
])

# ---------------------------------------------------------------- cadences

with onglets[0]:
    st.caption(
        "Cadence de référence = capacité de la ligne complète, goulot inclus. "
        "Elle évolue quand la capacité évolue, jamais pour expliquer une "
        "contre-performance."
    )
    articles = [a[0] for a in conn.execute(
        "SELECT code FROM article WHERE actif = 1 ORDER BY code"
    ).fetchall()]
    if not articles:
        st.info(
            "Aucun article n'est encore connu. Les articles apparaissent "
            "automatiquement au premier import, ou se créent dans l'onglet "
            "« Articles et familles »."
        )
    else:
        article = st.selectbox("Article", articles, key="cadence_article")
        modifie = referentiel_widget.bloc_referentiel(
            conn,
            titre=f"Cadence de {article}",
            table="cadence",
            cles={"article_code": article, "ligne_id": ligne["id"]},
            champs={"valeur_ppm": {"libelle": "Cadence (UVC par minute)",
                                   "type": "nombre", "minimum": 0.01, "pas": 0.5}},
            colonnes_frise={"valeur_ppm": "Cadence (ppm)"},
            cle_widget=f"cadence_{article}",
            avertissement="Les périodes antérieures conserveront l'ancienne cadence. "
                          "Les comparaisons avant/après ne seront pas directement "
                          "lisibles : utilisez la lecture à cadence constante.",
        )
        if modifie:
            st.rerun()

        st.divider()
        st.markdown("**Cadences en vigueur, tous articles**")
        vigueur = pd.read_sql_query(
            "SELECT article_code AS Article, valeur_ppm AS 'Cadence (ppm)',"
            " date_debut AS 'Depuis le' FROM cadence"
            " WHERE ligne_id = ? AND date_fin IS NULL ORDER BY article_code",
            conn, params=(ligne["id"],),
        )
        st.dataframe(vigueur, width="stretch", hide_index=True)

# ---------------------------------------------------------------- calendrier

with onglets[1]:
    st.caption(
        "Temps d'ouverture (To) et temps requis (Tr) par jour de semaine. "
        "Un calendrier non tenu à jour fait plonger le TRG sans raison visible : "
        "c'est le maillon faible de l'outil."
    )
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    jour_choisi = st.selectbox("Jour de la semaine", range(7),
                               format_func=lambda i: jours[i].capitalize())
    modifie = referentiel_widget.bloc_referentiel(
        conn,
        titre=f"Horaires du {jours[jour_choisi]}",
        table="calendrier_type",
        cles={"ligne_id": ligne["id"], "jour_semaine": jour_choisi},
        champs={
            "to_min": {"libelle": "Temps d'ouverture (minutes)", "type": "entier",
                       "maximum": 1440},
            "tr_min": {"libelle": "Temps requis (minutes)", "type": "entier",
                       "maximum": 1440},
        },
        colonnes_frise={"to_min": "To (min)", "tr_min": "Tr (min)"},
        cle_widget=f"calendrier_{jour_choisi}",
        avertissement="Le temps requis ne peut pas dépasser le temps d'ouverture.",
    )
    if modifie:
        st.rerun()

    st.divider()
    st.markdown("**Journées exceptionnelles** — fériés, arrêt annuel, journées atypiques")
    with st.form("exception_calendrier"):
        colonnes = st.columns(4)
        jour_exception = colonnes[0].date_input("Date", value=date.today())
        to_exception = colonnes[1].number_input("To (minutes)", value=0,
                                                min_value=0, max_value=1440)
        tr_exception = colonnes[2].number_input("Tr (minutes)", value=0,
                                                min_value=0, max_value=1440)
        motif_exception = colonnes[3].text_input("Motif", placeholder="Férié")
        if st.form_submit_button("Enregistrer la journée"):
            if tr_exception > to_exception:
                st.error(
                    "Le temps requis ne peut pas dépasser le temps d'ouverture "
                    f"({tr_exception} > {to_exception} minutes)."
                )
            else:
                conn.execute(
                    "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min, motif)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT(ligne_id, date) DO UPDATE SET"
                    " to_min = excluded.to_min, tr_min = excluded.tr_min,"
                    " motif = excluded.motif",
                    (ligne["id"], jour_exception.isoformat(), int(to_exception),
                     int(tr_exception), motif_exception.strip() or None),
                )
                conn.commit()
                st.success(f"Journée du {jour_exception:%d/%m/%Y} enregistrée.")

    exceptions = pd.read_sql_query(
        "SELECT date AS Date, to_min AS 'To (min)', tr_min AS 'Tr (min)',"
        " motif AS Motif FROM calendrier_exception WHERE ligne_id = ?"
        " ORDER BY date DESC LIMIT 50", conn, params=(ligne["id"],),
    )
    if not exceptions.empty:
        st.dataframe(exceptions, width="stretch", hide_index=True)

# ---------------------------------------------------------------- articles

with onglets[2]:
    st.caption(
        "Le rattachement d'un article à sa famille est historisé : une "
        "réorganisation du catalogue ne réécrit pas les analyses passées."
    )
    familles = conn.execute("SELECT id, libelle FROM famille ORDER BY libelle").fetchall()
    with st.form("creer_famille"):
        nouvelle = st.text_input("Nouvelle famille", placeholder="Famille A")
        if st.form_submit_button("Créer la famille") and nouvelle.strip():
            try:
                conn.execute(
                    "INSERT INTO famille (code, libelle) VALUES (?, ?)",
                    (nouvelle.strip().upper().replace(" ", "-"), nouvelle.strip()),
                )
                conn.commit()
                st.success(f"Famille « {nouvelle} » créée.")
                st.rerun()
            except Exception as erreur:
                commun.signaler(
                    f"La famille « {nouvelle} » existe déjà ou n'a pas pu être créée.",
                    erreur,
                )

    articles = [a[0] for a in conn.execute(
        "SELECT code FROM article ORDER BY code"
    ).fetchall()]
    if articles and familles:
        article = st.selectbox("Article", articles, key="famille_article")
        modifie = referentiel_widget.bloc_referentiel(
            conn,
            titre=f"Famille de {article}",
            table="article_famille",
            cles={"article_code": article},
            champs={"famille_id": {
                "libelle": "Famille", "type": "choix",
                "options": [f["id"] for f in familles],
            }},
            colonnes_frise={"famille_id": "Famille (identifiant)"},
            cle_widget=f"famille_{article}",
        )
        if modifie:
            st.rerun()
        st.caption(
            "Familles : "
            + ", ".join(f"{f['id']} = {f['libelle']}" for f in familles)
        )
    else:
        st.info("Créez au moins une famille et importez des articles pour commencer.")

# ---------------------------------------------------------------- motifs

with onglets[3]:
    st.caption(
        "La catégorie d'un motif pilote la cascade : un arrêt propre est retranché "
        "du temps requis, un arrêt hors requis du temps d'ouverture. Reclasser un "
        "motif prend effet à une date, sans toucher au passé."
    )
    catalogue = pd.read_sql_query(
        "SELECT m.id AS Identifiant, m.libelle AS Motif, mc.categorie AS Catégorie,"
        " mc.famille AS 'Famille de cause', m.date_fin AS 'Retiré le'"
        " FROM motif_arret m"
        " LEFT JOIN motif_classement mc ON mc.motif_id = m.id AND mc.date_fin IS NULL"
        " ORDER BY m.libelle", conn,
    )
    st.dataframe(catalogue, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Créer un motif**")
    with st.form("creer_motif"):
        colonnes = st.columns(3)
        libelle_motif = colonnes[0].text_input("Libellé", placeholder="Bourrage")
        categorie = colonnes[1].selectbox(
            "Catégorie", ["ARRET_PROPRE", "HORS_REQUIS"],
            format_func=lambda v: "Arrêt propre — aléa subi, retranché du temps requis"
            if v == "ARRET_PROPRE"
            else "Hors requis — retranché du temps d'ouverture",
        )
        famille_cause = colonnes[2].selectbox(
            "Famille de cause (facultative)",
            [None, "MECANIQUE", "ELECTRIQUE", "PROCESS", "MATIERE", "HUMAIN",
             "ORGANISATION", "QUALITE"],
            format_func=lambda v: "Non renseignée" if v is None else v.capitalize(),
        )
        arbre = elements.elements_en_service(conn, ligne["id"], date.today())
        rattachement = st.selectbox(
            "Rattacher à", [None] + [e["id"] for e in arbre],
            format_func=lambda v: "Motif global (proposé partout)" if v is None
            else next(e["libelle"] for e in arbre if e["id"] == v),
        )
        if st.form_submit_button("Créer le motif") and libelle_motif.strip():
            proches = motifs.libelles_proches(conn, libelle_motif)
            if proches:
                st.warning(
                    "Des motifs proches existent déjà : "
                    + ", ".join(f"« {m['libelle']} »" for m in proches[:5])
                    + ". Créer un doublon rendra le Pareto illisible. "
                    "Renommez votre motif si l'un d'eux convient."
                )
            try:
                motifs.creer_motif(
                    conn,
                    code=libelle_motif.strip().upper().replace(" ", "-")[:40],
                    libelle=libelle_motif.strip(), categorie=categorie,
                    date_debut=date.today(),
                    commentaire="Création depuis le référentiel",
                    auteur="utilisateur", famille=famille_cause,
                    element_id=rattachement,
                )
            except ErreurMetier as erreur:
                st.error(str(erreur))
            else:
                st.success(f"Motif « {libelle_motif} » créé.")
                st.rerun()

    st.divider()
    st.markdown("**Fusionner deux doublons**")
    tous = conn.execute("SELECT id, libelle FROM motif_arret ORDER BY libelle").fetchall()
    if len(tous) >= 2:
        with st.form("fusion_motifs"):
            colonnes = st.columns(2)
            garde = colonnes[0].selectbox(
                "Motif à conserver", [m["id"] for m in tous],
                format_func=lambda v: next(m["libelle"] for m in tous if m["id"] == v),
            )
            absorbe = colonnes[1].selectbox(
                "Motif à absorber", [m["id"] for m in tous], index=1,
                format_func=lambda v: next(m["libelle"] for m in tous if m["id"] == v),
            )
            justification = st.text_input("Motif de la fusion (obligatoire)")
            if st.form_submit_button("Fusionner"):
                if not justification.strip():
                    st.error("La fusion doit être justifiée par un commentaire.")
                else:
                    try:
                        nombre = motifs.fusionner_motifs(
                            conn, garde, absorbe, justification, "utilisateur"
                        )
                    except ErreurMetier as erreur:
                        st.error(str(erreur))
                    else:
                        st.success(
                            f"Fusion effectuée : {nombre} arrêt(s) réaffecté(s). "
                            "Aucun indicateur de la cascade n'a bougé."
                        )
                        st.rerun()

# ---------------------------------------------------------------- composition

with onglets[4]:
    st.caption(
        "L'arborescence sert à analyser l'origine des arrêts, jamais à calculer "
        "la cascade : déplacer un arrêt d'un élément à un autre ne change aucun "
        "indicateur. Un équipement utilisé se retire, il ne se supprime pas."
    )
    afficher_retires = st.checkbox("Afficher les éléments retirés du service")
    tous_elements = conn.execute(
        "SELECT * FROM element_ligne WHERE ligne_id = ? ORDER BY chemin",
        (ligne["id"],),
    ).fetchall()
    visibles = [
        dict(e) for e in tous_elements
        if afficher_retires or e["date_fin"] is None
    ]
    if not visibles:
        st.info("Aucun élément déclaré. Commencez par créer une zone.")
    else:
        arbre_affiche = []
        for element in visibles:
            profondeur = element["chemin"].strip("/").count("/")
            arbre_affiche.append({
                "Élément": "    " * profondeur + element["libelle"],
                "Type": element["type"].capitalize(),
                "En service depuis": element["date_debut"],
                "Retiré le": element["date_fin"] or "",
                "Arrêts rattachés": elements.nb_arrets(conn, element["id"]),
            })
        st.dataframe(arbre_affiche, width="stretch", hide_index=True)

    st.markdown("**Ajouter un élément**")
    with st.form("ajouter_element"):
        colonnes = st.columns(4)
        libelle_element = colonnes[0].text_input("Libellé", placeholder="Zone 1")
        type_element = colonnes[1].selectbox("Type", elements.TYPES_VALIDES,
                                             format_func=str.capitalize)
        en_service = [e for e in visibles if e["date_fin"] is None]
        parent = colonnes[2].selectbox(
            "Rattaché à", [None] + [e["id"] for e in en_service],
            format_func=lambda v: "Racine (zone)" if v is None
            else next(e["libelle"] for e in en_service if e["id"] == v),
        )
        depuis = colonnes[3].date_input("En service depuis", value=date.today())
        if st.form_submit_button("Ajouter") and libelle_element.strip():
            try:
                elements.ajouter_element(
                    conn, ligne["id"], parent,
                    code=libelle_element.strip().upper().replace(" ", "-")[:40],
                    libelle=libelle_element.strip(), type_element=type_element,
                    date_debut=depuis,
                )
            except ErreurMetier as erreur:
                st.error(str(erreur))
            else:
                st.success(f"« {libelle_element} » ajouté.")
                st.rerun()

    if visibles:
        st.markdown("**Retirer un élément du service**")
        with st.form("retirer_element"):
            colonnes = st.columns(3)
            en_service = [e for e in visibles if e["date_fin"] is None]
            a_retirer = colonnes[0].selectbox(
                "Élément", [e["id"] for e in en_service],
                format_func=lambda v: next(
                    e["libelle"] for e in en_service if e["id"] == v),
            ) if en_service else None
            date_retrait = colonnes[1].date_input("Retiré le", value=date.today())
            justification = colonnes[2].text_input("Motif du retrait")
            if st.form_submit_button("Retirer du service") and a_retirer:
                try:
                    elements.retirer_element(
                        conn, a_retirer, date_retrait,
                        justification.strip() or "Retrait du service", "utilisateur",
                    )
                except ErreurMetier as erreur:
                    st.error(str(erreur))
                else:
                    st.success(
                        "Élément retiré. Les analyses passées sont inchangées et "
                        "les arrêts lui restent attribués."
                    )
                    st.rerun()

# ---------------------------------------------------------------- paramètres datés

with onglets[5]:
    st.caption(
        "Ces paramètres entrent dans le calcul : les changer sans date d'effet "
        "recalculerait rétroactivement des mois de TRS. Ils sont donc datés."
    )
    modifie = referentiel_widget.bloc_referentiel(
        conn,
        titre="Mode de calcul du temps requis",
        table="parametre_date",
        cles={"cle": "MODE_TR"},
        champs={"valeur": {"libelle": "Mode", "type": "choix",
                           "options": ["FIXE", "CALCULE"]}},
        colonnes_frise={"valeur": "Mode"},
        cle_widget="mode_tr",
        rappel="FIXE : le temps requis vient du calendrier ; les arrêts hors requis "
               "sont affichés mais non retranchés. CALCULE : le temps requis est "
               "déduit des arrêts hors requis réellement déclarés — à n'activer que "
               "lorsque cette saisie est fiable et exhaustive.",
        avertissement="Le taux de charge (TC) se lit différemment selon le mode.",
    )
    if modifie:
        st.rerun()

    st.divider()
    modifie = referentiel_widget.bloc_referentiel(
        conn,
        titre="Début d'historique exploitable",
        table="parametre_date",
        cles={"cle": "DATE_DEBUT_HISTORIQUE"},
        champs={"valeur": {"libelle": "Date (AAAA-MM-JJ)", "type": "texte"}},
        colonnes_frise={"valeur": "Depuis"},
        cle_widget="debut_historique",
        rappel="Les données antérieures restent en base mais sont exclues de toutes "
               "les analyses : publier un TRS calculé avec des cadences supposées "
               "serait un chiffre faux présenté comme un fait.",
    )
    if modifie:
        st.rerun()

# ---------------------------------------------------------------- journal

with onglets[6]:
    st.caption(
        "Qui a changé quoi, quand, et pourquoi. C'est la page à ouvrir pour "
        "comprendre une rupture de courbe."
    )
    journal = referentiel_widget.journal_modifications(conn)
    if journal.empty:
        st.info("Aucune modification de référentiel enregistrée pour l'instant.")
    else:
        st.dataframe(journal, width="stretch", hide_index=True)

conn.close()
