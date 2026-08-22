"""Blocs de lecture des indicateurs (CDC §7.0).

Registre : instrument de mesure. Ce qui est recherché ici, c'est la hiérarchie
de lecture — on doit voir le chiffre principal avant les autres, et distinguer
d'un coup d'œil ce qui est mesuré de ce qui ne l'est pas. Pas de jauge, pas de
dégradé, pas de couleur décorative.
"""

from __future__ import annotations

import streamlit as st

from ui import theme

DEFINITIONS = {
    "TRS": "Ce que la ligne a produit, rapporté à ce qu'elle aurait pu produire "
           "pendant le temps où elle devait tourner. Tu / Tr.",
    "TRG": "Rapporté au temps d'ouverture : intègre donc le niveau de charge. Tu / To.",
    "TRE": "Rapporté aux 24 heures de la journée. Tu / Tt.",
    "TC": "Part du temps d'ouverture pendant laquelle la ligne devait produire. Tr / To.",
    "TS": "Part de la journée pendant laquelle l'atelier est ouvert. To / Tt.",
    "DO": "Part du temps requis pendant laquelle la ligne a effectivement tourné. Tf / Tr.",
    "TP": "Vitesse tenue par rapport à la cadence de référence. Tn / Tf.",
    "TQ": "Part de la production qui est bonne. Tu / Tn.",
    "taux_realisation": "Quantité produite rapportée à la quantité planifiée.",
}


def indicateur_principal(resultat: dict, unite: str = "UVC") -> None:
    """Le TRS en tête, avec la lecture en quantités qui le rend vérifiable.

    Deux façons de dire la même chose : le taux, et la comparaison
    « produit / produisible » que chacun peut refaire à la calculatrice.
    """
    with st.container(border=True):
        colonnes = st.columns([1, 2])
        with colonnes[0]:
            st.metric("TRS de la période", theme.format_taux(resultat["TRS"]),
                      help=DEFINITIONS["TRS"])
        with colonnes[1]:
            produite = resultat.get("qte_produite") or 0
            produisible = (resultat["Tu"] and produite / resultat["Tu"] * resultat["Tr"]) or 0
            if produisible:
                ecart = produite - produisible
                st.markdown(
                    f"**{theme.format_nombre(produite)} {unite} produites** sur "
                    f"**{theme.format_nombre(produisible)} {unite} produisibles** "
                    f"pendant le temps requis — soit "
                    f"{'+' if ecart >= 0 else '−'}"
                    f"{theme.format_nombre(abs(ecart))} {unite}."
                )
                st.caption(
                    "Ce rapport est exactement le TRS : il se vérifie à la calculatrice."
                )
            else:
                st.markdown("**Production non mesurable sur cette période.**")


def cartes_cascade(resultat: dict) -> None:
    """Les trois taux de la cascade, avec ce qui manque quand ils ne sont pas mesurés."""
    st.markdown("**Décomposition du TRS**")
    colonnes = st.columns(3)
    manques = {
        "DO": "Aucun arrêt saisi sur la période.",
        "TP": "Aucun arrêt saisi : la performance ne peut pas être isolée.",
        "TQ": "Pas de compteur en sortie d'ensacheuse.",
    }
    libelles = {"DO": "Disponibilité DO", "TP": "Performance TP", "TQ": "Qualité TQ"}
    for colonne, cle in zip(colonnes, ("DO", "TP", "TQ")):
        with colonne:
            valeur = resultat.get(cle)
            st.metric(libelles[cle], theme.format_taux(valeur), help=DEFINITIONS[cle])
            if valeur is None:
                st.caption(manques[cle])
    if resultat.get("TRS") is not None and all(
        resultat.get(c) is not None for c in ("DO", "TP", "TQ")
    ):
        st.caption("TRS = TQ × TP × DO — le produit des trois redonne le TRS.")


def cartes_contexte(resultat: dict) -> None:
    """Les taux qui situent la période sans mesurer la performance de la ligne."""
    colonnes = st.columns(4)
    for colonne, (cle, libelle) in zip(colonnes, (
        ("TRG", "TRG"), ("TRE", "TRE"),
        ("TC", "Charge TC"), ("TS", "Stratégique TS"),
    )):
        colonne.metric(libelle, theme.format_taux(resultat.get(cle)),
                       help=DEFINITIONS.get(cle))


def bandeau_niveau(resultat: dict) -> None:
    """Ce qui est mesuré, ce qui ne l'est pas, et ce qu'il faudrait collecter."""
    niveau = resultat["niveau_donnees"]
    intitules = {
        1: "Niveau 1 sur 3 — TRS, TRG et TRE exacts, décomposition indisponible",
        2: "Niveau 2 sur 3 — arrêts saisis, disponibilité et performance mesurées",
        3: "Niveau 3 sur 3 — cascade entièrement décomposée",
    }
    manque = []
    if not resultat.get("arrets_saisis"):
        manque.append("la saisie des arrêts, avec horodatage de début et de fin")
    if not resultat.get("qualite_mesuree"):
        manque.append("un compteur en sortie d'ensacheuse")
    texte = intitules[niveau]
    if manque:
        texte += ". Pour aller plus loin : " + " et ".join(manque) + "."
    st.caption(texte)


def alertes(resultat: dict, limite: int | None = None) -> None:
    """Alertes de la période, les plus importantes d'abord."""
    liste = resultat.get("alertes", [])
    if not liste:
        return
    montrees = liste if limite is None else liste[:limite]
    for alerte in montrees:
        st.warning(alerte)
    reste = len(liste) - len(montrees)
    if reste > 0:
        with st.expander(f"{reste} autre(s) signalement(s)"):
            for alerte in liste[len(montrees):]:
                st.write("- " + alerte)
