"""Indicateurs TQ, TP, DO, TC, TS, TRS, TRG, TRE (CDC §5.2).

Règles non négociables :

- le TRS se calcule sans les arrêts : TRS = Tu / Tr = quantité produite /
  (cadence x Tr). Les arrêts et le compteur d'ensacheuse ne servent qu'à le
  DÉCOMPOSER (TQ, TP, DO) ;
- un indicateur non décomposé n'est jamais affiché à 100 % : il vaut None
  (« non mesuré ») tant que les données pour le mesurer n'existent pas ;
- dénominateur nul -> None, jamais 0 ni division par zéro ;
- TP et TRS ne sont jamais plafonnés : un dépassement de 100 % est un signal
  (cadence de référence à réévaluer), pas un bug.
"""

from __future__ import annotations

import pandas as pd

COLONNES_TEMPS = ("Tt", "To", "Tr", "Tf", "Tn", "Tu")


def _ratio(numerateur: float, denominateur: float) -> float | None:
    """Division sûre : None si le dénominateur est nul (affiché « n/a »)."""
    if denominateur is None or numerateur is None or denominateur == 0:
        return None
    return numerateur / denominateur


def sommer_temps(df_cascade: pd.DataFrame) -> dict:
    """Somme les temps des jours agrégeables d'une cascade journalière.

    On agrège des temps, jamais des taux (CDC §5.3). Les jours exclus
    (hors service, hors historique, données manquantes) ne sont pas sommés ;
    ils sont comptés à part pour l'affichage.
    """
    agregables = df_cascade[df_cascade["etat"].isin(("OK", "FERME"))]
    temps = {colonne: float(agregables[colonne].sum()) for colonne in COLONNES_TEMPS}
    temps["qte_produite"] = float(agregables["qte_produite"].sum())
    temps["qte_planifiee"] = float(agregables["qte_planifiee"].sum())
    temps["nb_arrets_saisis"] = int(agregables["nb_arrets_saisis"].sum())
    temps["lignes_sans_cadence"] = int(agregables["lignes_sans_cadence"].sum())
    temps["avertissement_horodatage"] = bool(agregables["avertissement_horodatage"].any())
    jours_ok = agregables[agregables["etat"] == "OK"]
    production = jours_ok[jours_ok["qte_produite"] > 0]
    temps["qualite_mesuree"] = bool(len(production) > 0 and production["qualite_mesuree"].all())
    temps["nb_jours_ok"] = int(len(jours_ok))
    temps["nb_jours_donnees_manquantes"] = int(
        (df_cascade["etat"] == "DONNEES_MANQUANTES").sum()
    )
    temps["nb_jours_sans_cadence"] = int((df_cascade["etat"] == "SANS_CADENCE").sum())
    return temps


def calculer_indicateurs(temps: dict) -> dict:
    """Dérive les huit indicateurs d'un dictionnaire de temps sommés.

    Niveaux de données (CDC §5.0) :
    - niveau 1 (aucun arrêt saisi, pas de compteur) : TRS, TRG, TRE exacts ;
      TQ, TP, DO -> None, jamais 1,0 ;
    - niveau 2 (arrêts saisis) : DO et TP mesurés ; TP contient encore la
      non-qualité tant que le compteur manque ;
    - niveau 3 (compteur d'ensacheuse) : TQ mesuré, TP purgé des pertes qualité.
    """
    arrets_saisis = temps.get("nb_arrets_saisis", 0) > 0
    qualite_mesuree = bool(temps.get("qualite_mesuree", False))

    indicateurs = {
        # Toujours calculables (niveau 1) — strictement égaux aux ratios de quantités.
        "TRS": _ratio(temps["Tu"], temps["Tr"]),
        "TRG": _ratio(temps["Tu"], temps["To"]),
        "TRE": _ratio(temps["Tu"], temps["Tt"]),
        "TC": _ratio(temps["Tr"], temps["To"]),
        "TS": _ratio(temps["To"], temps["Tt"]),
        # Décomposition — uniquement quand les données existent.
        "DO": _ratio(temps["Tf"], temps["Tr"]) if arrets_saisis else None,
        "TP": _ratio(temps["Tn"], temps["Tf"]) if arrets_saisis else None,
        "TQ": _ratio(temps["Tu"], temps["Tn"]) if qualite_mesuree else None,
        "taux_realisation": _ratio(temps["qte_produite"], temps["qte_planifiee"]),
        "arrets_saisis": arrets_saisis,
        "qualite_mesuree": qualite_mesuree,
    }
    indicateurs["niveau_donnees"] = 1 + int(arrets_saisis) + int(qualite_mesuree)
    indicateurs["alertes"] = _alertes(temps, indicateurs)
    return indicateurs


def _alertes(temps: dict, indicateurs: dict) -> list[str]:
    """Signaux à afficher — jamais de plafonnement silencieux (CDC §5.4)."""
    alertes = []
    if indicateurs["TRS"] is not None and indicateurs["TRS"] > 1:
        alertes.append(
            "La quantité produite dépasse la quantité produisible sur le temps requis : "
            "cadence de référence sous-évaluée ou calendrier incorrect."
        )
    if indicateurs["TP"] is not None and indicateurs["TP"] > 1:
        alertes.append(
            "La ligne a tenu plus que la capacité de référence : "
            "cadence à réévaluer. Ce n'est pas un défaut de mesure."
        )
    if temps.get("nb_jours_sans_cadence"):
        alertes.append(
            f"{temps['nb_jours_sans_cadence']} jour(s) de production sans aucune cadence "
            "de référence : le TRS n'y est pas calculable et ces journées sont exclues "
            "des indicateurs. Les quantités restent enregistrées. Pour les mesurer, "
            "définissez une cadence de référence pour ces articles."
        )
    elif temps.get("lignes_sans_cadence"):
        alertes.append(
            f"{temps['lignes_sans_cadence']} ligne(s) de production sans cadence applicable, "
            "exclue(s) de tous les calculs de temps."
        )
    if temps.get("nb_jours_donnees_manquantes"):
        alertes.append(
            f"{temps['nb_jours_donnees_manquantes']} jour(s) requis sans données importées, "
            "exclu(s) des moyennes (un import oublié n'est pas une contre-performance)."
        )
    if temps.get("avertissement_horodatage"):
        alertes.append(
            "Des arrêts sans horodatage : durées additionnées sans détection "
            "des chevauchements possibles."
        )
    if not indicateurs["arrets_saisis"]:
        alertes.append(
            "DO et TP non mesurés : aucun arrêt saisi sur la période. "
            "Le TRS reste exact ; seule sa décomposition manque."
        )
    if not indicateurs["qualite_mesuree"]:
        alertes.append(
            "TQ non mesuré : compteur de sortie d'ensacheuse absent. Écart de cadence "
            "et non-qualité restent regroupés."
        )
    return alertes


def indicateurs_periode(df_cascade: pd.DataFrame) -> dict:
    """Temps sommés + indicateurs d'une période, en un appel."""
    temps = sommer_temps(df_cascade)
    return {**temps, **calculer_indicateurs(temps)}
