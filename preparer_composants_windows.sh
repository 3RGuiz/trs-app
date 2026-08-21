#!/bin/sh
# Prépare le dossier "composants" à emporter sur le poste Windows.
#
# À lancer depuis le poste de développement (macOS), qui a accès à internet.
# Le dossier produit permet d'installer l'application sur un poste Windows
# SANS accès à PyPI — situation courante en production.
#
#   ./preparer_composants_windows.sh
#
# Copiez ensuite le dossier du projet, dossier "composants" inclus, sur le poste
# Windows, puis lancez-y preparer_poste.bat.

set -e
cd "$(dirname "$0")"

VERSION_PYTHON="${1:-3.12}"
DESTINATION="composants"

if [ ! -x .venv/bin/python ]; then
    echo "Environnement de développement absent : lancez d'abord"
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "Téléchargement des composants Windows (Python ${VERSION_PYTHON}, 64 bits)..."
rm -rf "$DESTINATION"
mkdir -p "$DESTINATION"

# --platform/--only-binary : on récupère les roues Windows depuis macOS.
.venv/bin/python -m pip download \
    --dest "$DESTINATION" \
    --requirement requirements.txt \
    --platform win_amd64 \
    --python-version "$VERSION_PYTHON" \
    --only-binary=:all:

nombre=$(ls -1 "$DESTINATION" | wc -l | tr -d ' ')
taille=$(du -sh "$DESTINATION" | cut -f1)

echo
echo "Terminé : ${nombre} fichier(s), ${taille} dans ./${DESTINATION}"
echo
echo "Emportez le dossier du projet avec ce dossier « composants »,"
echo "puis lancez preparer_poste.bat sur le poste Windows."
