"""Import d'une extraction ERP (CDC §7.2).

Séquence imposée : choisir le fichier, associer les colonnes, choisir le mode
d'écriture, LIRE L'APERÇU DES DIFFÉRENCES, puis valider. Aucune écriture n'a
lieu avant cette validation.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from core import importer
from core.erreurs import ConfirmationRequise, ErreurMetier, ImportInvalide
from ui import commun, theme

FICHIER_PROFIL = commun.RACINE / "data" / "profil_mapping.json"

LIBELLES_CHAMPS = {
    "date": "Date de production",
    "article_code": "Code article",
    "of_numero": "N° d'ordre de fabrication",
    "qte_planifiee": "Quantité planifiée",
    "qte_produite": "Quantité produite",
    "qte_ensachee": "Compteur sortie ensacheuse",
}

st.title("Importer une extraction ERP")

conn = commun.ouvrir()
ligne = commun.exiger_ligne(conn)
commun.bandeau_fraicheur(conn, ligne["id"])


def charger_profil() -> dict:
    """Profil de mapping mémorisé : un seul mapping à faire, une fois (CDC §6.3)."""
    if FICHIER_PROFIL.exists():
        try:
            return json.loads(FICHIER_PROFIL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def enregistrer_profil(profil: dict) -> None:
    FICHIER_PROFIL.parent.mkdir(parents=True, exist_ok=True)
    FICHIER_PROFIL.write_text(
        json.dumps(profil, ensure_ascii=False, indent=2), encoding="utf-8"
    )


profil_memorise = charger_profil()

fichier = st.file_uploader(
    "Choisir le fichier d'extraction", type=["xlsx", "xls", "csv"],
    help="Format attendu : Excel de préférence, CSV accepté.",
)

if fichier is None:
    st.info(
        "Sélectionnez une extraction pour commencer. Le fichier n'est lu qu'une "
        "fois, à l'import : les écrans d'analyse lisent ensuite la base, jamais "
        "le fichier. Il peut donc être archivé ou supprimé ensuite."
    )
    historique = pd.read_sql_query(
        "SELECT date_import, fichier, mode_ecriture, periode_debut, periode_fin,"
        " nb_ajouts, nb_maj, nb_suppressions, nb_rejets"
        " FROM import_log ORDER BY id DESC LIMIT 20", conn,
    )
    if not historique.empty:
        st.subheader("Historique des imports")
        st.dataframe(historique.rename(columns={
            "date_import": "Importé le", "fichier": "Fichier",
            "mode_ecriture": "Mode", "periode_debut": "Du", "periode_fin": "Au",
            "nb_ajouts": "Ajouts", "nb_maj": "Mises à jour",
            "nb_suppressions": "Suppressions", "nb_rejets": "Rejets",
        }), width="stretch", hide_index=True)
        st.caption(
            "L'annulation du dernier import restaure la sauvegarde prise juste "
            "avant celui-ci. Elle demande de fermer puis rouvrir l'application."
        )
    st.stop()

# Le fichier téléversé est copié sur disque : c'est lui qui porte l'empreinte
# et qui sera archivé sous data/imports/ après un import réussi.
dossier_travail = commun.RACINE / "data" / "imports"
dossier_travail.mkdir(parents=True, exist_ok=True)
chemin_temporaire = dossier_travail / f"_en_cours{Path(fichier.name).suffix}"
chemin_temporaire.write_bytes(fichier.getbuffer())
empreinte = importer.calculer_empreinte(chemin_temporaire)

try:
    brut, profil = importer.lire_fichier(chemin_temporaire, profil_memorise)
except ImportInvalide as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        f"Le fichier {fichier.name} n'a pas pu être lu. Vérifiez qu'il s'agit "
        "bien d'une extraction Excel ou CSV, non protégée par mot de passe.",
        erreur,
    )

st.subheader("Aperçu du fichier")
st.caption(
    f"{len(brut)} ligne(s) lue(s)"
    + (f" — en-tête détecté ligne {profil['entete_ligne'] + 1}"
       if profil.get("entete_ligne") is not None else "")
    + (f" — encodage {profil['encodage']}" if profil.get("encodage") else "")
)
st.dataframe(brut.head(10), width="stretch")

# ---------------------------------------------------------------- mapping

st.subheader("Associer les colonnes")
colonnes_fichier = ["(aucune)"] + [str(c) for c in brut.columns]
mapping_memorise = profil_memorise.get("mapping", {})
mapping = {}
grille = st.columns(3)
for numero, (champ, libelle) in enumerate(LIBELLES_CHAMPS.items()):
    defaut = mapping_memorise.get(champ)
    index = colonnes_fichier.index(defaut) if defaut in colonnes_fichier else 0
    if index == 0:
        # Proposition automatique par ressemblance de nom.
        for position, colonne in enumerate(colonnes_fichier):
            if champ.split("_")[-1].lower() in str(colonne).lower():
                index = position
                break
    obligatoire = champ in importer.CHAMPS_OBLIGATOIRES
    choix = grille[numero % 3].selectbox(
        libelle + (" *" if obligatoire else ""), colonnes_fichier, index=index,
        key=f"map_{champ}",
    )
    if choix != "(aucune)":
        mapping[champ] = choix
st.caption("Les champs marqués d'une étoile sont obligatoires.")

# ---------------------------------------------------------------- mode d'écriture

st.subheader("Mode d'écriture")
mode = st.radio(
    "Que faire des données déjà présentes sur la période du fichier ?",
    ["UPSERT", "REMPLACEMENT_PERIODE", "REIMPORT_COMPLET"],
    format_func=lambda v: {
        "UPSERT": "Ajout et mise à jour — les lignes absentes du fichier sont conservées",
        "REMPLACEMENT_PERIODE": "Remplacement de période — reflète les annulations d'OF",
        "REIMPORT_COMPLET": "Réimport complet — chargement initial ou reconstruction",
    }[v],
    index=["UPSERT", "REMPLACEMENT_PERIODE", "REIMPORT_COMPLET"].index(
        profil_memorise.get("mode", "UPSERT")
    ),
)
fenetre = st.number_input(
    "Fenêtre de rafraîchissement (jours)", value=importer.FENETRE_RAFRAICHISSEMENT_JOURS,
    min_value=1, max_value=3650, step=1,
    help="En remplacement de période, seuls les N derniers jours du fichier sont "
         "réellement remplacés. Au-delà, les données sont considérées comme figées.",
    disabled=(mode != "REMPLACEMENT_PERIODE"),
)

try:
    normalise = importer.normaliser(brut, mapping, profil)
except (ImportInvalide, ErreurMetier) as erreur:
    commun.signaler(str(erreur), erreur)
except Exception as erreur:
    commun.signaler(
        "Les colonnes associées n'ont pas pu être converties. Vérifiez que chaque "
        "champ pointe vers la bonne colonne du fichier.", erreur,
    )

# ---------------------------------------------------------------- aperçu des différences

st.subheader("Aperçu des différences")
try:
    apercu = importer.apercu_differences(
        conn, normalise, ligne["id"], mode=mode,
        fenetre_jours=int(fenetre) if mode == "REMPLACEMENT_PERIODE" else None,
        empreinte=empreinte,
    )
except Exception as erreur:
    commun.signaler("L'aperçu des différences n'a pas pu être calculé.", erreur)

if apercu["deja_importe"]:
    st.warning(
        f"Ce fichier a déjà été importé le {apercu['deja_importe']}. "
        "Le réimporter ne changera rien."
    )

if apercu["periode_debut"]:
    st.markdown(
        f"**Période couverte : "
        f"{date.fromisoformat(apercu['periode_debut']):%d/%m/%Y} → "
        f"{date.fromisoformat(apercu['periode_fin']):%d/%m/%Y}**"
    )
compteurs = st.columns(5)
compteurs[0].metric("Lignes nouvelles", apercu["nb_ajouts"])
compteurs[1].metric("Lignes modifiées", apercu["nb_maj"])
compteurs[2].metric("Lignes inchangées", apercu["nb_inchangees"])
compteurs[3].metric("Disparaîtraient", apercu["nb_suppressions"])
compteurs[4].metric("Rejets", apercu["nb_rejets"])

if apercu["nb_hors_fenetre"]:
    st.info(
        f"{apercu['nb_hors_fenetre']} ligne(s) du fichier sont antérieures à la "
        "fenêtre de rafraîchissement : elles sont ignorées, les données de cette "
        "période restent figées."
    )
if apercu["rejets"]:
    with st.expander(f"Détail des {len(apercu['rejets'])} rejet(s)"):
        st.dataframe(
            [{"Motif du rejet": r["motif"]} for r in apercu["rejets"]],
            width="stretch", hide_index=True,
        )
if apercu["articles_inconnus"]:
    st.info(
        "Articles inconnus, qui seront créés en famille « À classer » : "
        + ", ".join(apercu["articles_inconnus"])
    )
if apercu["sans_cadence"]:
    st.warning(
        f"{len(apercu['sans_cadence'])} couple(s) article/date sans cadence "
        "applicable. Ces lignes seront importées mais exclues des calculs de "
        "temps tant qu'aucune cadence ne les couvre."
    )

# ---------------------------------------------------------------- validation

st.subheader("Valider l'import")
st.caption(
    "Une sauvegarde de la base est prise automatiquement avant l'écriture. "
    "Elle permet d'annuler cet import si nécessaire."
)
confirmer = st.checkbox(
    "Je confirme les suppressions et le réimport éventuel",
    help="Nécessaire si l'import supprime plus de 10 % des lignes de la période, "
         "ou si ce fichier a déjà été importé.",
)

if st.button("Importer maintenant", type="primary"):
    try:
        rapport = importer.importer_production(
            conn, commun.chemin_base(), normalise, ligne["id"], mode=mode,
            fichier=fichier.name, empreinte=empreinte,
            fenetre_jours=int(fenetre) if mode == "REMPLACEMENT_PERIODE" else None,
            confirmer_suppressions=confirmer, confirmer_reimport=confirmer,
        )
    except ConfirmationRequise as erreur:
        st.warning(
            str(erreur) + "\n\nCochez la case de confirmation ci-dessus pour continuer."
        )
        st.stop()
    except ErreurMetier as erreur:
        commun.signaler(str(erreur), erreur)
    except Exception as erreur:
        commun.signaler(
            "L'import a échoué et la base n'a pas été modifiée. La sauvegarde "
            "prise avant l'écriture reste disponible.", erreur,
        )

    profil_memorise = {**profil, "mapping": mapping, "mode": mode}
    enregistrer_profil(profil_memorise)
    # Archivage du fichier sous son empreinte, pour pouvoir auditer un import ancien.
    chemin_temporaire.replace(
        dossier_travail / f"{empreinte[:12]}{Path(fichier.name).suffix}"
    )

    st.success(
        f"Import terminé : {rapport['nb_ajouts']} ajout(s), "
        f"{rapport['nb_maj']} mise(s) à jour, "
        f"{rapport['nb_suppressions']} suppression(s), "
        f"{rapport['nb_rejets']} rejet(s)."
    )
    if rapport["jours_sans_calendrier"]:
        st.warning(
            f"{len(rapport['jours_sans_calendrier'])} jour(s) de la période n'ont "
            "aucune entrée au calendrier : leurs indicateurs resteront muets. "
            "Complétez le calendrier depuis la page Référentiel."
        )
    for anomalie in rapport["anomalies"]:
        st.warning(anomalie)
    st.caption("Le mapping des colonnes est mémorisé pour le prochain import.")

conn.close()
