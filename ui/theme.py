"""Formatage français et constantes visuelles (CDC §7.0).

Registre : instrument de mesure. Aucun emoji, pas de couleur décorative.
Les temps sont stockés et calculés en minutes ; seul l'affichage est en h min.
"""

from __future__ import annotations

ESPACE_INSECABLE = "\u00a0"

# Palette validée pour la lisibilité, y compris en vision déficiente des couleurs.
COULEUR_TEMPS_CONSERVE = "#2a78d6"
COULEUR_PERTE = "#eb6834"
COULEUR_TROISIEME_SERIE = "#1baf7a"
COULEUR_ENCRE = "#0b0b0b"
COULEUR_ENCRE_SECONDAIRE = "#52514e"
COULEUR_AXES = "#898781"
COULEUR_GRILLE = "#e1e0d9"
COULEUR_FOND_GRAPHIQUE = "#fcfcfb"

# Statuts — réservés à l'écart aux objectifs, toujours accompagnés d'un libellé.
COULEUR_CONFORME = "#0ca30c"
COULEUR_VIGILANCE = "#fab219"
COULEUR_ALERTE = "#ec835a"
COULEUR_CRITIQUE = "#d03b3b"


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
