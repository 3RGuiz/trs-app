"""Point d'entrée : identité visuelle et navigation.

Ce fichier ne calcule rien et n'affiche aucune donnée. Il pose le décor —
titre, logo, menu — puis délègue à la page choisie. Les écrans vivent dans
app_pages/.

Le logo et les visuels de l'entreprise ne sont pas versionnés (CLAUDE.md,
règle 9) : ils se déposent dans assets/, et l'application fonctionne sans eux.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui import theme

RACINE = Path(__file__).parent
ASSETS = RACINE / "assets"

st.set_page_config(
    page_title="Rendement et TRS",
    page_icon=str(theme.chemin_favicon(ASSETS)) if theme.chemin_favicon(ASSETS) else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.appliquer_identite(ASSETS)

PAGES = [
    st.Page("app_pages/0_Dashboard.py", title="Dashboard",
            icon=":material/dashboard:", default=True),
    st.Page("app_pages/4_TRS.py", title="TRS", icon=":material/speed:"),
    st.Page("app_pages/3_Rendement.py", title="Rendement",
            icon=":material/inventory_2:"),
    st.Page("app_pages/6_Arrets.py", title="Arrêts", icon=":material/build:"),
    st.Page("app_pages/1_Import.py", title="Import",
            icon=":material/upload_file:"),
    st.Page("app_pages/2_Referentiel.py", title="Référentiel",
            icon=":material/settings_applications:"),
    st.Page("app_pages/5_Parametres.py", title="Paramètres",
            icon=":material/tune:"),
    st.Page("app_pages/7_Aide.py", title="Aide", icon=":material/help:"),
]

st.navigation(
    {
        "Analyse": PAGES[:4],
        "Données et réglages": PAGES[4:],
    }
).run()
