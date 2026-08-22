"""Graphiques de l'application (CDC §7.0).

Règles transverses appliquées ici :
- jamais de double axe des ordonnées ;
- la couleur porte une information ou n'est pas là — deux couleurs seulement
  pour la cascade : temps conservé et perte ;
- le vert/orange du livre AYEL & DAVIER n'est pas repris : ce couple est
  indistinguable en vision protanope ;
- chaque graphique a une vue tableau équivalente, construite par l'appelant.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core import agregation

from ui import theme

# Ordre imposé de la cascade (CDC §7.0).
ORDRE_CASCADE = ("Tt", "To", "Tr", "Tf", "Tn", "Tu")

LIBELLES_TEMPS = {
    "Tt": "Tt — temps total",
    "To": "To — temps d'ouverture",
    "Tr": "Tr — temps requis",
    "Tf": "Tf — temps de fonctionnement",
    "Tn": "Tn — temps net",
    "Tu": "Tu — temps utile",
}


def _mise_en_forme(figure: go.Figure, hauteur: int = 420) -> go.Figure:
    figure.update_layout(
        height=hauteur,
        paper_bgcolor=theme.COULEUR_FOND_GRAPHIQUE,
        plot_bgcolor=theme.COULEUR_FOND_GRAPHIQUE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif",
                  color=theme.COULEUR_ENCRE, size=13),
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
    )
    figure.update_xaxes(gridcolor=theme.COULEUR_GRILLE, linecolor=theme.COULEUR_AXES,
                        color=theme.COULEUR_AXES, zeroline=False)
    figure.update_yaxes(gridcolor=theme.COULEUR_GRILLE, linecolor=theme.COULEUR_AXES,
                        color=theme.COULEUR_AXES, zeroline=False)
    return figure


def cascade_des_temps(temps: dict) -> go.Figure:
    """Waterfall horizontal Tt -> To -> Tr -> Tf -> Tn -> Tu.

    Chaque palier porte son libellé et sa valeur écrits : la couleur ne porte
    jamais l'information seule.
    """
    valeurs = [float(temps.get(nom) or 0) for nom in ORDRE_CASCADE]
    libelles = [LIBELLES_TEMPS[nom] for nom in ORDRE_CASCADE]

    figure = go.Figure(go.Bar(
        x=valeurs,
        y=libelles,
        orientation="h",
        marker_color=theme.COULEUR_TEMPS_CONSERVE,
        text=[theme.format_duree(v) for v in valeurs],
        textposition="outside",
        hovertemplate="%{y} : %{text}<extra></extra>",
    ))
    figure.update_yaxes(autorange="reversed")
    figure.update_xaxes(title="Minutes")
    return _mise_en_forme(figure)


def pertes_par_etage(temps: dict) -> go.Figure:
    """Barres horizontales des pertes entre étages de la cascade.

    Ce que chaque étage retranche, en minutes : c'est la lecture qui désigne
    où passe le temps.
    """
    etages = []
    for amont, aval, libelle in (
        ("Tt", "To", "Hors ouverture"),
        ("To", "Tr", "Hors requis (pauses, nettoyage, démarrage)"),
        ("Tr", "Tf", "Arrêts propres"),
        ("Tf", "Tn", "Écart de cadence"),
        ("Tn", "Tu", "Non-qualité"),
    ):
        perte = float(temps.get(amont) or 0) - float(temps.get(aval) or 0)
        if perte > 0:
            etages.append((libelle, perte))
    if not etages:
        return _mise_en_forme(go.Figure(), hauteur=200)

    libelles, valeurs = zip(*etages)
    figure = go.Figure(go.Bar(
        x=list(valeurs), y=list(libelles), orientation="h",
        marker_color=theme.COULEUR_PERTE,
        text=[theme.format_duree(v) for v in valeurs],
        textposition="outside",
        hovertemplate="%{y} : %{text}<extra></extra>",
    ))
    figure.update_yaxes(autorange="reversed")
    figure.update_xaxes(title="Minutes perdues")
    return _mise_en_forme(figure, hauteur=320)


def evolution_trs(
    df_periodes: pd.DataFrame,
    changements_cadence: list[str] | None = None,
    objectif: float | None = None,
    maille: str = "semaine",
) -> go.Figure:
    """Courbe d'évolution du TRS, avec repères aux changements de cadence.

    Une seule échelle d'ordonnée. Les repères verticaux sont indispensables :
    sans eux, une baisse due au relèvement de la référence se lit comme une
    dégradation (CDC §4.2).
    """
    df = df_periodes.dropna(subset=["TRS"])
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=df["periode"], y=df["TRS"] * 100,
        mode="lines+markers", line=dict(color=theme.COULEUR_TEMPS_CONSERVE, width=2),
        marker=dict(size=8),
        hovertemplate="%{x} : %{y:.1f} %<extra></extra>",
    ))
    if objectif is not None:
        figure.add_hline(
            y=objectif * 100, line_dash="dot", line_color=theme.COULEUR_ENCRE_SECONDAIRE,
            annotation_text=f"Objectif {theme.format_taux(objectif)}",
            annotation_position="top left",
        )
    # Repères de changement de cadence. L'axe des abscisses étant catégoriel,
    # la position se donne par l'index de la catégorie : passer le libellé fait
    # échouer Plotly, qui tente d'en calculer une moyenne numérique.
    categories = list(df["periode"])
    for changement in (changements_cadence or []):
        cle = agregation.cle_periode(pd.Series([changement]), maille).iloc[0]
        if cle in categories:
            figure.add_vline(
                x=categories.index(cle), line_dash="dash",
                line_color=theme.COULEUR_PERTE,
                annotation_text="Changement de cadence",
                annotation_position="top right",
            )
    figure.update_yaxes(title="TRS (%)", rangemode="tozero")
    return _mise_en_forme(figure)


def pareto_arrets(df_pareto: pd.DataFrame, limite: int = 8) -> go.Figure:
    """Pareto des arrêts : barres triées et courbe de cumul sur une seule échelle.

    Au-delà de `limite` catégories, le reste est regroupé en « Autres » plutôt
    que d'inventer des couleurs.
    """
    if df_pareto.empty:
        return _mise_en_forme(go.Figure(), hauteur=200)

    df = df_pareto.sort_values("duree_min", ascending=False).reset_index(drop=True)
    if len(df) > limite:
        tete = df.iloc[:limite].copy()
        reste = df.iloc[limite:]
        autres = pd.DataFrame([{
            "libelle": f"Autres ({len(reste)})",
            "duree_min": reste["duree_min"].sum(),
            "nb_arrets": reste["nb_arrets"].sum(),
        }])
        df = pd.concat([tete, autres], ignore_index=True)

    total = df["duree_min"].sum()
    cumul = df["duree_min"].cumsum() / total * 100 if total else df["duree_min"] * 0

    figure = go.Figure()
    figure.add_trace(go.Bar(
        x=df["libelle"], y=df["duree_min"],
        marker_color=theme.COULEUR_PERTE,
        text=[theme.format_duree(v) for v in df["duree_min"]],
        textposition="outside",
        hovertemplate="%{x}<br>%{text}<extra></extra>",
    ))
    # Cumul ramené à l'échelle des minutes : une seule échelle d'ordonnée.
    figure.add_trace(go.Scatter(
        x=df["libelle"], y=cumul / 100 * df["duree_min"].max(),
        mode="lines+markers", line=dict(color=theme.COULEUR_TEMPS_CONSERVE, width=2),
        marker=dict(size=8),
        customdata=cumul,
        hovertemplate="Cumul : %{customdata:.0f} %<extra></extra>",
    ))
    figure.update_yaxes(title="Minutes d'arrêt")
    return _mise_en_forme(figure)
