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
ACCENT_PRIMAIRE = "#0060ae"      # bleu de la charte
ACCENT_CHAUD = "#e8bf00"         # jaune de l'interface, assourdi
ACCENT_CHAUD_VIF = "#ffd400"     # jaune du logo, réservé aux aplats
ACCENT_VIF = "#f00000"           # rouge de la charte
ANTHRACITE = "#1e1f1c"
BORDURE_CHAUDE = "#c9a600"   # jaune assombri, pour border sur fond jaune

# Mise en page du logo dans la barre latérale. Le contour blanc est un padding :
# le fichier fourni n'ayant aucune marge transparente, sans lui le dessin
# toucherait le bord de la carte.
LARGEUR_LOGO = "90%"
LARGEUR_LOGO_MAX = "230px"
MARGE_LOGO = "0.85rem 1rem"
ARRONDI_LOGO = "0.9rem"


def reglages_logo(racine: Path) -> dict[str, str]:
    """Réglages d'affichage du logo, surchargeables depuis config.toml."""
    valeurs = {
        "logo_largeur": LARGEUR_LOGO,
        "logo_largeur_max": LARGEUR_LOGO_MAX,
        "logo_marge": MARGE_LOGO,
        "logo_arrondi": ARRONDI_LOGO,
    }
    config = racine / "config.toml"
    if config.exists():
        try:
            import tomllib
            declares = tomllib.loads(config.read_text(encoding="utf-8")).get("identite", {})
        except (tomllib.TOMLDecodeError, OSError):
            declares = {}
        for cle in valeurs:
            if isinstance(declares.get(cle), str):
                valeurs[cle] = declares[cle]
    return valeurs


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
    """Logo \u00e0 afficher, ou None s'il n'a pas \u00e9t\u00e9 d\u00e9pos\u00e9.

    Cherche d'abord le chemin d\u00e9clar\u00e9 dans config.toml \u2014 il peut \u00eatre absolu et
    pointer vers un dossier SharePoint synchronis\u00e9, de sorte qu'une mise \u00e0 jour
    de la charte se propage sans toucher \u00e0 l'application. \u00c0 d\u00e9faut, prend le
    premier fichier reconnu dans assets/.
    """
    racine = assets.parent
    config = racine / "config.toml"
    if config.exists():
        try:
            import tomllib
            declare = tomllib.loads(config.read_text(encoding="utf-8")).get(
                "identite", {}
            ).get("logo")
        except (tomllib.TOMLDecodeError, OSError):
            declare = None
        if declare:
            candidat = Path(declare)
            if not candidat.is_absolute():
                candidat = racine / candidat
            if candidat.exists():
                return candidat

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

    reglages = reglages_logo(assets.parent)
    logo = chemin_logo(assets)
    if logo is not None:
        # Fond blanc derrière le logo, comme sur l'intranet : la charte le pose
        # sur du blanc, jamais directement sur le jaune.
        st.logo(str(logo), size="large")

    st.html(
        f"""
        <style>
          /* En-tête de la barre : Streamlit y place le logo et le bouton de
             repli côte à côte, dans une bande de hauteur fixe. On libère la
             hauteur, on centre le logo, et le bouton passe hors du flux pour
             ne pas être repoussé sous l'image. */
          [data-testid="stSidebarHeader"] {{
              position: relative !important;
              height: auto !important;
              max-height: none !important;
              display: flex !important;
              justify-content: center !important;
              align-items: center !important;
              /* Gouttière à droite : elle réserve la place du bouton de repli,
                 qui sans elle se superpose au logo. */
              padding: 0.6rem 2.2rem 0.2rem 0.6rem !important;
              margin-bottom: 0.4rem !important;
          }}
          [data-testid="stSidebarCollapseButton"] {{
              position: absolute !important;
              top: 0.15rem;
              right: 0.1rem;
              z-index: 5;
          }}
          /* Dans la barre latérale, le logo porte le testid stSidebarLogo —
             et non stLogo, qui ne désigne que le logo de la page principale. */
          [data-testid="stSidebarLogo"], [data-testid="stLogo"] {{
              width: {reglages['logo_largeur']} !important;
              max-width: {reglages['logo_largeur_max']} !important;
              height: auto !important;
              max-height: none !important;
              object-fit: contain !important;
              object-position: center !important;
              display: block !important;
              margin: 0 auto !important;
              padding: {reglages['logo_marge']} !important;
              background: #ffffff !important;
              border-radius: {reglages['logo_arrondi']} !important;
              box-sizing: border-box !important;
          }}

          /* Chiffres alignés verticalement : indispensable pour comparer. */
          [data-testid="stMetricValue"] {{
              font-variant-numeric: tabular-nums;
              color: {ANTHRACITE};
          }}
          [data-testid="stMetricLabel"] {{ color: #52514e; }}
          table, [data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}

          /* Titres de section soulignés du jaune de la charte. st.subheader
             produit un h3, st.header un h2 : les deux sont visés. */
          [data-testid="stMainBlockContainer"] h2,
          [data-testid="stMainBlockContainer"] h3 {{
              border-bottom: 3px solid {ACCENT_CHAUD};
              padding-bottom: 0.2rem;
              display: inline-block;
          }}

          /* Sur fond jaune, l'encre reste noire — jamais de blanc sur jaune. */
          [data-testid="stSidebar"] button {{ color: {ANTHRACITE}; }}
          [data-testid="stSidebarNav"] a[aria-current="page"] {{
              background: rgba(255, 255, 255, 0.55);
              border-radius: 0.35rem;
              font-weight: 600;
          }}
          .stButton button[kind="primary"] {{
              color: {ANTHRACITE};
              border: 1px solid {BORDURE_CHAUDE};
          }}
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
