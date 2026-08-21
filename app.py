"""Page d'accueil : tableau de bord de synthèse (CDC §7.1).

Toute la logique vit dans core/ ; cette page ne fait qu'afficher.
"""

from __future__ import annotations

import logging
import tomllib
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from core import db, indicateurs, temps
from core.erreurs import ErreurMetier
from ui import theme

RACINE = Path(__file__).parent

# Streamlit est configuré avec showErrorDetails = "none" : rien ne s'affiche
# de lui-même en cas d'erreur. Tout problème doit donc être rattrapé ici et
# expliqué en français. Le détail technique part dans la console, pour le
# développeur, jamais à l'écran.
journal = logging.getLogger(__name__)


def signaler(message: str, erreur: Exception | None = None) -> None:
    """Affiche une erreur compréhensible et interrompt la page proprement."""
    if erreur is not None:
        journal.exception(message)
    st.error(message)
    st.stop()


def chemin_base() -> Path:
    """Chemin de la base, lu dans config.toml — jamais écrit en dur."""
    config = RACINE / "config.toml"
    if config.exists():
        contenu = tomllib.loads(config.read_text(encoding="utf-8"))
        return RACINE / contenu.get("base", {}).get("chemin", "data/trs.db")
    return RACINE / "data" / "trs.db"


st.set_page_config(page_title="Rendement et TRS", layout="wide")
st.title("Rendement et TRS de la ligne")

# Aucun st.stop() dans les blocs try : il lève une exception interne à
# Streamlit qu'un except large intercepterait par erreur.
try:
    conn = db.ouvrir_base(chemin_base())
except tomllib.TOMLDecodeError as erreur:
    signaler(
        "Le fichier de configuration config.toml est illisible. "
        "Corrigez-le ou supprimez-le pour revenir aux valeurs par défaut.",
        erreur,
    )
except ErreurMetier as erreur:
    signaler(str(erreur), erreur)
except Exception as erreur:
    signaler(
        f"Impossible d'ouvrir la base de données ({chemin_base()}). "
        "Vérifiez que le fichier existe, qu'il n'est pas ouvert par un autre "
        "programme, et que le dossier est accessible.",
        erreur,
    )

try:
    lignes = conn.execute(
        "SELECT * FROM ligne WHERE date_fin IS NULL ORDER BY code"
    ).fetchall()
except Exception as erreur:
    signaler(
        "La base de données est inutilisable : la liste des lignes de production "
        "n'a pas pu être lue. Restaurez une sauvegarde depuis la page Paramètres.",
        erreur,
    )

if not lignes:
    st.info(
        "La base est vide. Commencez par saisir le référentiel — ligne, cadences, "
        "calendrier — depuis la page Référentiel, puis importez une extraction ERP "
        "depuis la page Import. Pour développer sans données réelles : "
        "`python generer_donnees_test.py`."
    )
    st.stop()

ligne = lignes[0]

# ---------------------------------------------------------------- fraîcheur des données

derniere_production = conn.execute(
    "SELECT MAX(date) FROM production WHERE ligne_id = ?", (ligne["id"],)
).fetchone()[0]
dernier_import = conn.execute(
    "SELECT MAX(date_import) FROM import_log"
).fetchone()[0]

if derniere_production is None:
    st.warning("Aucune donnée de production importée. Passez par la page Import.")
    st.stop()

st.caption(
    f"Données à jour au {date.fromisoformat(derniere_production):%d/%m/%Y}"
    + (f" — dernier import le {dernier_import}" if dernier_import else "")
)
retard = (date.today() - date.fromisoformat(derniere_production)).days
if retard > 7:
    st.warning(
        f"Les données datent de {retard} jours. "
        "Une extraction plus récente est peut-être disponible."
    )

# ---------------------------------------------------------------- période analysée

col_debut, col_fin = st.columns(2)
defaut_fin = date.fromisoformat(derniere_production)
defaut_debut = defaut_fin - timedelta(days=29)
periode_debut = col_debut.date_input("Début de période", value=defaut_debut)
periode_fin = col_fin.date_input("Fin de période", value=defaut_fin)

if periode_debut is None or periode_fin is None:
    signaler("Renseignez une date de début et une date de fin pour la période analysée.")
if periode_fin < periode_debut:
    signaler(
        f"La fin de période ({periode_fin:%d/%m/%Y}) est antérieure à son début "
        f"({periode_debut:%d/%m/%Y}). Inversez les deux dates."
    )

try:
    df = temps.cascade_journaliere(conn, ligne["id"], periode_debut, periode_fin)
    resultat = indicateurs.indicateurs_periode(df)
except ErreurMetier as erreur:
    signaler(str(erreur), erreur)
except Exception as erreur:
    signaler(
        "Le calcul des indicateurs de la période a échoué. Vérifiez le référentiel "
        "— cadences et calendrier — depuis la page Référentiel, puis réessayez.",
        erreur,
    )

# ---------------------------------------------------------------- bandeau de capacité

if resultat["Tr"] > 0:
    st.subheader("Capacité et réalisation")
    colonnes = st.columns(3)
    colonnes[0].metric("Quantité produite",
                       theme.format_nombre(resultat["qte_produite"]) + " paquets")
    colonnes[1].metric("Temps requis cumulé", theme.format_duree(resultat["Tr"]))
    colonnes[2].metric("Taux de réalisation du plan",
                       theme.format_taux(resultat["taux_realisation"]))

# ---------------------------------------------------------------- indicateurs

st.subheader("Indicateurs de la période")
colonnes = st.columns(4)
colonnes[0].metric("TRS", theme.format_taux(resultat["TRS"]))
colonnes[1].metric("TRG", theme.format_taux(resultat["TRG"]))
colonnes[2].metric("TRE", theme.format_taux(resultat["TRE"]))
colonnes[3].metric("Taux de charge TC", theme.format_taux(resultat["TC"]))

colonnes = st.columns(4)
colonnes[0].metric("Disponibilité DO", theme.format_taux(resultat["DO"]))
colonnes[1].metric("Performance TP", theme.format_taux(resultat["TP"]))
colonnes[2].metric("Qualité TQ", theme.format_taux(resultat["TQ"]))
colonnes[3].metric("Taux stratégique TS", theme.format_taux(resultat["TS"]))

st.caption(
    f"Niveau de données : {resultat['niveau_donnees']} sur 3 — "
    "1 : TRS, TRG, TRE exacts ; 2 : arrêts saisis, DO et TP décomposés ; "
    "3 : compteur d'ensacheuse, TQ mesuré."
)

for alerte in resultat["alertes"]:
    st.warning(alerte)

conn.close()
