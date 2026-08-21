# Mettre l'application en service sur un poste Windows

Procédure à dérouler une seule fois par poste. Comptez une trentaine de minutes
la première fois, en incluant les vérifications.

Pour l'utilisateur final, le résultat est un **raccourci à double-cliquer** :
aucune commande à taper, aucun Python à connaître.

---

## Pourquoi pas un fichier `.exe` unique

La question se pose naturellement. Elle a été tranchée pour quatre raisons :

- un exécutable Windows ne peut pas être fabriqué depuis le poste de
  développement macOS : il faudrait une machine Windows dédiée ;
- les antivirus d'entreprise mettent fréquemment en quarantaine les
  exécutables Python non signés — le risque est bien plus élevé qu'avec un
  simple fichier de commandes ;
- l'application deviendrait figée : la moindre correction de libellé imposerait
  une recompilation, alors que le chapitre 4 de la notice prévoit qu'elle
  puisse évoluer sans développeur ;
- le gain serait nul pour l'utilisateur, qui double-clique de toute façon sur
  un raccourci.

Le dossier décrit ci-dessous se comporte donc comme un programme installé,
tout en restant lisible et modifiable.

---

## 1. Préparer les composants — sur le poste de développement

Beaucoup de postes de production n'ont pas accès à internet. Préparez donc les
composants à l'avance, depuis le Mac :

```bash
./preparer_paquets_windows.sh
```

Le script crée un dossier `paquets/` d'environ 90 Mo contenant les composants
au format Windows 64 bits. Il suppose Python 3.12 sur le poste cible ; pour une
autre version, passez-la en argument (`./preparer_paquets_windows.sh 3.11`).

Ce dossier n'est **pas** versionné : il se reconstruit à la demande.

---

## 2. Copier le dossier sur le poste Windows

Copiez le dossier du projet **entier** — dossier `paquets/` inclus — vers le
poste, par le SharePoint synchronisé ou une clé USB.

Deux règles à respecter :

- **installez l'application sur le disque local**, par exemple
  `C:\Applications\TRS`, et non dans le dossier SharePoint synchronisé. Le
  client de synchronisation peut copier la base de données pendant une écriture
  et la corrompre ;
- **ne copiez pas les dossiers `.venv` ni `data`** du poste de développement :
  le premier contient des composants macOS inutilisables sous Windows, le
  second des données de test.

---

## 3. Installer Python, si nécessaire

Si Python n'est pas déjà présent, demandez au service informatique d'installer
**Python 3.11 ou plus récent** depuis <https://www.python.org/downloads/windows/>,
en cochant **« Add Python to PATH »** pendant l'installation.

C'est la seule dépendance externe de l'application.

---

## 4. Préparer le poste

Double-cliquez sur **`preparer_poste.bat`**.

Le script trouve Python, crée l'environnement de l'application dans le dossier
`.venv`, installe les composants — depuis le dossier `paquets/` s'il est
présent, sinon depuis internet — puis vérifie que l'installation est complète.

À faire **une seule fois**. En cas d'échec, le message affiché indique quoi
faire ; les causes habituelles sont l'absence de Python et le manque de droits
d'écriture dans le dossier.

---

## 5. Démarrer l'application

Double-cliquez sur **`lancer.bat`**. Une fenêtre noire s'ouvre, puis le
navigateur affiche l'application.

Deux points à expliquer à l'utilisateur :

- **la fenêtre noire doit rester ouverte** pendant toute l'utilisation : c'est
  elle qui fait tourner l'application ;
- **pour quitter, on ferme cette fenêtre** — fermer l'onglet du navigateur ne
  suffit pas.

### Créer le raccourci sur le bureau

Clic droit sur `lancer.bat` → **Envoyer vers** → **Bureau (créer un raccourci)**.
Renommez le raccourci « Application TRS ». Vous pouvez lui donner une icône par
clic droit → Propriétés → Changer d'icône.

C'est ce raccourci que l'utilisateur emploiera au quotidien.

---

## 6. Recette — à faire avant de confier l'outil

Six vérifications, dans l'ordre :

1. `lancer.bat` démarre l'application et le navigateur s'ouvre ;
2. importer une **vraie** extraction ERP, non retouchée ;
3. vérifier que les quantités importées sont numériques et que les totaux
   correspondent à ceux du fichier source ;
4. lancer une sauvegarde vers le dossier SharePoint depuis la page Paramètres,
   puis vérifier que le fichier est bien arrivé ;
5. parcourir les écrans principaux et contrôler qu'aucun tableau ni libellé ne
   déborde ;
6. vérifier le calcul à la main sur une journée : quantité produite divisée par
   quantité produisible doit donner le TRS affiché.

Les captures d'écran de la notice utilisateur se prennent à cette occasion,
sur ce poste — pas sur le Mac de développement.

---

## 7. Si quelque chose bloque

| Symptôme | Cause probable | Ce qu'il faut faire |
|---|---|---|
| « Windows a protégé votre ordinateur » (SmartScreen) | Fichier venu d'internet, marqué comme tel | Clic sur « Informations complémentaires » → « Exécuter quand même ». Si le blocage persiste, c'est une règle d'entreprise : voir avec l'informatique |
| L'antivirus met `lancer.bat` en quarantaine | Politique de sécurité du poste | Demander une exception sur le dossier de l'application. Cela ne se règle pas avec du code |
| « L'application n'est pas encore installée » | `preparer_poste.bat` n'a pas été lancé, ou a échoué | Le relancer et lire le message affiché |
| « Aucun Python n'est installé sur ce poste » | Python absent ou non ajouté au PATH | Étape 3 ci-dessus |
| L'installation échoue sans internet | Dossier `paquets/` absent | Le récupérer depuis le poste de développement (étape 1) |
| Le navigateur affiche une page d'erreur générique | Une erreur inattendue de l'application | Le détail est écrit dans la fenêtre noire : le transmettre au responsable de l'outil |
| L'application semble figée après une modification du code | Une ancienne instance tourne encore | Fermer toutes les fenêtres noires, puis relancer |

---

## 8. Mettre à jour l'application

1. Fermer l'application (fermer la fenêtre noire) ;
2. sauvegarder `data\trs.db` par simple copie ;
3. remplacer les fichiers de code par la nouvelle version, **sans toucher au
   dossier `data`** ;
4. si les composants ont changé, relancer `preparer_poste.bat` ;
5. relancer `lancer.bat` et vérifier qu'une période connue affiche toujours le
   même TRS.
