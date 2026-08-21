# Application de calcul de rendement et de TRS

Application locale, mono-poste, sans serveur. Calcule le taux de réalisation et les
indicateurs TRS / TRG / TRE d'une ligne de production à partir d'une extraction ERP.
Les quantités sont exprimées en UVC, les cadences en UVC par minute, les temps
en minutes.

## Installation

Développement (macOS, Linux) :

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Poste d'exploitation (Windows) : double-clic sur `preparer_poste.bat`, une seule
fois. La procédure complète, y compris l'installation sans accès à internet, est
dans `docs/Mise_en_service_Windows.md`.

## Lancement

```bash
./lancer.sh                 # macOS, Linux
```

Sous Windows : double-clic sur `lancer.bat`, ou sur le raccourci créé au bureau.
Une fenêtre annonce le démarrage, puis reste à l'écran : elle fait tourner
l'application et porte le bouton « Arrêter l'application ».

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
