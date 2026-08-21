# Application de calcul de rendement et de TRS

Application locale, mono-poste, sans serveur. Calcule le taux de réalisation et les
indicateurs TRS / TRG / TRE d'une ligne de production à partir d'une extraction ERP.

## Installation

```bash
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run app.py        # ou lancer.bat sous Windows, lancer.sh sous macOS
```

## Tests

```bash
pytest -q
```

## Premier lancement

L'application démarre sur une base vide. Un assistant guide la saisie du référentiel :
composition de la ligne, cadences de référence, calendrier des temps d'ouverture et requis.
Aucune donnée métier n'est livrée avec le code.

## Organisation du code

```
core/     Python pur, sans dépendance à Streamlit — testable isolément
ui/       Composants d'affichage réutilisables
pages/    Écrans Streamlit : affichage et saisie uniquement
tests/    pytest
data/     Base SQLite et fichiers de travail (non versionnés)
```

Les conventions et règles de développement sont dans `CLAUDE.md`.
