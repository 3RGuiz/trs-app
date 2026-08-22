"""Formatage français et constantes visuelles (CDC §7.0).

Registre : instrument de mesure. Aucun emoji, pas de couleur décorative.
Les temps sont stockés et calculés en minutes ; seul l'affichage est en h min.
"""

from __future__ import annotations

from pathlib import Path

ESPACE_INSECABLE = "\u00a0"

# ---------------------------------------------------------------- identit\u00e9

# Couleurs d'identit\u00e9, reprises de la charte. Elles habillent l'application \u2014
# en-t\u00eate, navigation, accents \u2014 mais ne servent jamais \u00e0 coder une donn\u00e9e :
# les s\u00e9ries de graphiques gardent la palette fonctionnelle plus bas, valid\u00e9e
# pour rester lisible en vision d\u00e9ficiente des couleurs (CDC \u00a77.0).
ACCENT_PRIMAIRE = "#0069b4"      # bleu
ACCENT_CHAUD = "#ffc800"         # jaune
ACCENT_VIF = "#e30613"           # rouge
ANTHRACITE = "#2b2a28"

# Noms de fichiers reconnus dans assets/, par ordre de pr\u00e9f\u00e9rence. Les visuels
# de marque ne sont pas versionn\u00e9s : l'application se passe d'eux si absents.
NOMS_LOGO = ("logo.png", "logo.svg", "logo.jpg", "logo.jpeg", "logo.webp")
NOMS_FAVICON = ("favicon.png", "favicon.ico", "logo.png")


# Palette validée pour la lisibilité, y compris en vision déficiente des couleurs.
COULEUR_TEMPS_CONSERVE = ACCENT_PRIMAIRE
COULEUR_PERTE = "#eb6834"
COULEUR_TROISIEME_SERIE = "#1baf7a"
COULEUR_ENCRE = ANTHRACITE
COULEUR_ENCRE_SECONDAIRE = "#52514e"
COULEUR_AXES = "#898781"
COULEUR_GRILLE = "#e1e0d9"
COULEUR_FOND_GRAPHIQUE = "#fcfcfb"

# Statuts — réservés à l'écart aux objectifs, toujours accompagnés d'un libellé.
COULEUR_CONFORME = "#0ca30c"
COULEUR_VIGILANCE = "#fab219"
COULEUR_ALERTE = "#ec835a"
COULEUR_CRITIQUE = ACCENT_VIF


def chemin_logo(assets: Path) -> Path | None:
    """Logo \u00e0 afficher dans la barre lat\u00e9rale, ou None s'il n'a pas \u00e9t\u00e9 d\u00e9pos\u00e9."""
    for nom in NOMS_LOGO:
        candidat = assets / nom
        if candidat.exists():
            return candidat
    return None


def chemin_favicon(assets: Path) -> Path | None:
    for nom in NOMS_FAVICON:
        candidat = assets / nom
        if candidat.exists():
            return candidat
    return None


def appliquer_identite(assets: Path) -> None:
    """Pose le logo et les quelques retouches visuelles de l'identit\u00e9.

    Importe streamlit \u00e0 l'appel : ce module reste utilisable hors interface,
    notamment pour le formatage des nombres.
    """
    import streamlit as st

    logo = chemin_logo(assets)
    if logo is not None:
        st.logo(str(logo), size="large")

    # Retouches minimales : une barre d'accent sous les titres de section, et
    # des chiffres tabulaires pour que les colonnes s'alignent verticalement.
    st.html(
        f"""
        <style>
          [data-testid="stMetricValue"] {{
              font-variant-numeric: tabular-nums;
              color: {ANTHRACITE};
          }}
          [data-testid="stMetricLabel"] {{ color: #52514e; }}
          h2 {{
              border-bottom: 3px solid {ACCENT_CHAUD};
              padding-bottom: 0.2rem;
              display: inline-block;
          }}
          [data-testid="stSidebarNav"] a[aria-current="page"] {{
              border-left: 3px solid {ACCENT_PRIMAIRE};
          }}
          table, [data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
        </style>
        """
    )

def format_nombre(valeur: float | None, decimales: int = 0) -> str:
    """13500 -> « 13 500 » (espace insécable, virgule décimale)."""
    if valeur is None:
        return "n/a"
    texte = f"{valeur:,.{decimales}f}"
    return texte.replace(",", ESPACE_INSECABLE).replace(".", ",")


def format_taux(valeur: float | None, decimales: int = 1) -> str:
    """0.7719 -> « 77,2 % ». None -> « non mesuré » (jamais 100 %)."""
    if valeur is None:
        return "non mesuré"
    return format_nombre(valeur * 100, decimales) + f"{ESPACE_INSECABLE}%"


def format_duree(minutes: float | None) -> str:
    """570 -> « 9 h 30 ». Stockage et calcul restent en minutes."""
    if minutes is None:
        return "n/a"
    heures, restantes = divmod(round(minutes), 60)
    if heures == 0:
        return f"{restantes} min"
    return f"{heures}{ESPACE_INSECABLE}h{ESPACE_INSECABLE}{restantes:02d}"
