# CLAUDE.md — Application TRS ligne de conditionnement

Contrat de travail pour toute session de développement sur ce dépôt.
La spécification fonctionnelle complète est dans **`CDC_Application_TRS.md`** — la lire avant
toute modification du modèle de données ou du moteur de calcul. Ce fichier-ci ne répète pas
le CDC : il fixe les conventions et les règles qu'on ne renégocie pas.

---

## Contexte en trois lignes

Application locale (Streamlit + pandas + SQLite), mono-poste, sans serveur, qui calcule
le rendement et le TRS d'une **ligne de conditionnement complète** à partir d'une extraction ERP.
Développée en sprint court par une personne seule, destinée à vivre plusieurs années
et à être reprise par quelqu'un d'autre.

---

## Commandes

```bash
# Installation
pip install -r requirements.txt

# Lancer l'application
streamlit run app.py          # ou double-clic sur lancer.bat sous Windows

# Tests — à lancer avant toute fin de tâche
pytest -q

# Régénérer un jeu de données fictives
python generer_donnees_test.py --reset
```

---

## Les neuf règles à ne jamais enfreindre

Elles correspondent aux erreurs qui coûtent cher et ne se rattrapent pas après coup.
Si une demande semble les contredire, **s'arrêter et demander** plutôt que de trancher seul.

1. **Le passé ne change jamais.**
   Aucun référentiel ne se modifie en place. Un changement = clôture de la ligne en vigueur
   + insertion d'une nouvelle, avec date d'effet. Tout calcul résout les valeurs *à la date
   de la production concernée*, jamais « la valeur actuelle ».
   Concerné : cadences, calendrier (To/Tr), catégories de motifs d'arrêt, familles d'articles,
   formats, ligne et éléments, motifs et leur classement, objectifs, `parametre_date`.

2. **On agrège des temps, jamais des taux.**
   Le TRS d'une semaine se calcule en sommant Tu, Tn, Tf, Tr, To, Tt *puis* en divisant.
   Une moyenne de TRS journaliers est fausse — sur un jeu réaliste, l'écart atteint 14 points.

3. **La cadence de référence est la capacité de la ligne complète**, goulot conditionnement
   inclus. Valeurs réelles : **24 ppm en juin 2026, 30 ppm depuis le 01/07/2026**.
   Elle n'est jamais ajustée après coup pour expliquer une contre-performance ; elle évolue
   quand la capacité évolue.
   **Historique exploitable à partir du 01/06/2026** (`date_debut_historique`) : les données
   antérieures sont stockées mais exclues de toutes les analyses.

4. **Cadence en ppm, temps en minutes, quantités en paquets.**
   `quantité / cadence` donne directement des minutes. **Aucun facteur 60 dans `core/`.**

4 ter. **Pas de TRS par article.**
   `Tu` se ventile par article, `Tr` non — l'ERP ne donne pas les horaires d'OF. Toute
   répartition inventée de Tr redonne le taux de réalisation sous un autre nom, ou le même
   chiffre pour tous les articles. Par article et par famille : taux de réalisation, quantité
   produite, Tu. **Jamais** de TRS, TRG ou TRE (CDC §5.2 ter).

4 bis. **Le TRS se calcule sans les arrêts.**
   `TRS = quantité produite / (cadence × Tr)`, strictement égal à `Tu / Tr`. La saisie des
   arrêts et le compteur d'ensacheuse ne servent qu'à **décomposer** la perte en TQ, TP, DO.
   Aujourd'hui l'ERP ne donne qu'une quantité produite et aucun arrêt n'est saisi : le
   niveau 1 (TRS, TRG, TRE exacts) est complet et livrable seul (CDC §5.0).
   **Ne jamais afficher un indicateur non décomposé comme valant 100 %** — afficher
   « non mesuré » et dire ce qui manque.

5. **Pas de double comptage.**
   Les écarts de cadence et la non-qualité sont *calculés par différence*, jamais saisis.
   En `MODE_TR = 'FIXE'`, les arrêts hors requis sont affichés mais **non retranchés**.

6. **Le TRS est celui de la LIGNE, pas d'une machine.**
   Un arrêt peut venir de n'importe quel élément — friteuse, vibrants, tunnel d'enrobage,
   ensacheuse, contrôles, encartonneuse, palettisation, utilités, organisation.
   `element_id` sert à l'**analyse** (Pareto), jamais au calcul : déplacer un arrêt d'un
   élément à un autre ne doit changer aucun indicateur.
   Deux corollaires :
   - les arrêts se combinent par **union d'intervalles**, jamais par somme — deux sections
     en panne en même temps n'arrêtent la ligne qu'une fois ;
   - seuls les arrêts à `arrete_ligne = 1` entrent dans la cascade ; ceux absorbés par un
     tampon sont conservés pour le Pareto et n'affectent aucun temps.

7. **Rien de ce que l'utilisateur a saisi ne se supprime.**
   Un équipement ou un motif déjà utilisé se **retire** (`date_fin`), jamais ne se supprime.
   La suppression physique n'est autorisée que sur un élément sans aucun arrêt rattaché et
   sans descendant — sinon, erreur explicite proposant le retrait. Jamais de suppression
   en cascade, jamais de réaffectation automatique des arrêts vers le parent.

8. **La composition de la ligne et le catalogue de motifs appartiennent à l'utilisateur.**
   Arborescence des éléments et liste des motifs se créent et se modifient **depuis
   l'interface**, jamais en dur dans le code. Ne livrer que les 11 motifs globaux du
   référentiel AYEL & DAVIER ; tout le reste vient du terrain.
   Les motifs sont rattachés aux éléments (héritage par les ancêtres + motifs globaux) et
   s'ajoutent à la volée depuis l'écran de saisie d'un arrêt, avec recherche de libellés
   proches avant création pour éviter les doublons.

9. **Le dépôt GitHub ne porte que du code.**
   Il sert à l'historique des versions et au retour arrière, pas à documenter le projet.
   Le code ne fait donc **aucune référence à l'entreprise, à ses produits ou à ses procédés**.
   Notes, cahier des charges détaillé et paramètres réels vivent dans le vault, hors du dépôt.

---

## Ce qui va dans le dépôt, et pourquoi

Le dépôt existe pour une raison simple : pouvoir revenir à une version antérieure quand une
modification tourne mal, et garder une trace ordonnée de l'évolution du projet.

| Dans le dépôt | Hors du dépôt |
|---|---|
| Code, tests, `requirements.txt`, lanceurs | Vault Obsidian : journal, décisions, cahier des charges détaillé |
| `CHANGELOG.md`, `README.md` | Base `data/trs.db` et sauvegardes |
| Ce fichier | Extractions ERP |

**Conséquence sur le code** — elle découle déjà de la règle 8, qui veut que la ligne et les
motifs viennent de l'interface :

- **aucune donnée d'amorçage métier** : l'application démarre avec une base vide, l'utilisateur
  saisit son arborescence, ses cadences et son calendrier au premier lancement ; seuls les
  motifs génériques du référentiel AYEL & DAVIER sont livrés ;
- **jeux de test synthétiques** : `ART-001`, `Famille A`, `Zone 1 / Machine 1`, avec des
  cadences et des horaires manifestement fictifs ;
- **chemins configurables**, jamais écrits en dur.

En cas de doute sur un terme destiné au dépôt, **s'abstenir et demander** : retirer quelque
chose de l'historique Git demande de réécrire le dépôt.

---

## Mémoire et import

La base SQLite **est** la mémoire de l'application. Les indicateurs se calculent toujours
depuis la base, **jamais** en relisant le fichier ERP : un fichier importé peut être supprimé
sans conséquence. L'historique se construit par accumulation d'imports successifs.

L'extraction ERP est produite manuellement. Trois voies d'actualisation (CDC §6.1) :
bouton + explorateur (`st.file_uploader`, à faire dans le sprint), dossier surveillé sur
le SharePoint synchronisé, puis éventuellement tâche planifiée.

Trois règles d'import à ne pas contourner :

- **Rien ne s'écrit sans aperçu des différences** — lignes ajoutées, modifiées, supprimées,
  rejetées — validé par l'utilisateur.
- **Une sauvegarde automatique est prise avant chaque import.** « Annuler le dernier import »
  restaure cette sauvegarde ; ne jamais tenter d'inverser un upsert ligne à ligne.
- **La fraîcheur des données est affichée en permanence** : date de production la plus récente,
  date du dernier import, alerte au-delà de 7 jours.

---

## Architecture

```
core/    Python pur — AUCUN import de streamlit. C'est la règle qui rend le projet testable.
ui/      Composants d'affichage réutilisables (thème, widget référentiel, graphiques).
pages/   Pages Streamlit : affichage et saisie uniquement, zéro logique de calcul.
tests/   pytest. Les invariants du CDC §5.5 sont bloquants.
```

`core/historisation.py` est le socle : `valider_non_chevauchement`, `cloturer_et_inserer`,
`resoudre`, `resoudre_en_masse`. **Tout nouveau référentiel passe par ces fonctions**,
jamais par du SQL écrit à la main dans un module métier.

`ui/referentiel_widget.py` est son pendant côté interface, réutilisé par les onglets du
référentiel. Ne pas dupliquer un formulaire de saisie historisée. Seul l'onglet
« Composition de la ligne » fait exception : il a besoin d'une vue en arbre.

---

## macOS en développement, Windows en exploitation

- `pathlib.Path` partout, jamais de séparateur écrit en dur.
- **Le format d'import principal est le `.xlsx`** (`engine="calamine"`, repli `openpyxl`).
  Ses pièges vérifiés : en-tête pas en première ligne, nombres stockés en texte, formules
  sans valeur en cache. Voir CDC §6.2.
- **Les CSV réels viennent de Windows en français** : point-virgule, cp1252 ou UTF-8-BOM,
  virgule décimale, espaces insécables comme séparateur de milliers, dates jj/mm/aaaa.
  Lire en `dtype=str` puis convertir explicitement ; parser les dates avec un format explicite ;
  **asserter le type numérique après conversion**. Sans cette assertion, une colonne reste
  du texte et `.sum()` concatène au lieu d'additionner — erreur silencieuse et fausse.
  Jamais de `errors="coerce"` silencieux sur une quantité.
- `lancer.bat` n'est pas testable sur macOS : maintenir un `lancer.sh` pour le développement.
- `busy_timeout` sur la connexion SQLite (verrous transitoires dus aux antivirus Windows).
- Les captures d'écran de la notice se prennent sous Windows (CDC §7 bis).

---

## Conventions de code

- Python 3.11+, code et commentaires **en français**, noms de variables métier explicites
  (`temps_requis`, pas `tr`). Les abréviations TQ/TP/DO/TC/TS restent pour l'affichage.
- Type hints sur les signatures publiques de `core/`.
- Pas d'ORM, pas de migrations Alembic, pas de Docker. Le projet doit rester lisible
  et modifiable par une personne seule.
- Erreurs métier : classes dédiées dans `core/erreurs.py`, messages en français orientés
  utilisateur. **Jamais de stack trace brute affichée à l'écran.**
- Toute fonction de `core/` doit être appelable sans base de données peuplée
  (injection de DataFrames ou de connexion, pas de singleton global).

---

## Interface

Registre : instrument de mesure, pas tableau de bord grand public. Sobre, mais agréable à
utiliser — pas austère.

- **Aucun emoji**, nulle part. Pas de dégradés, pas d'animation, pas de jauges circulaires.
- **Icônes bienvenues** : un jeu unique en traits (Lucide / Feather / Material Symbols
  Outlined), monochrome à l'encre secondaire, 16–20 px, embarqué dans `assets/` — jamais
  un CDN. Toujours accompagnées d'un libellé écrit ; une icône seule n'identifie ni une
  action ni un statut. Usage fonctionnel (navigation, actions, statuts), pas décoratif.
- **Images bienvenues quand elles expliquent** : schéma de la cascade, synoptique de la ligne,
  photo de l'installation, logo. Fichiers locaux.
- Critère d'arbitrage : *est-ce que cet élément aide à lire ou à agir plus vite ?*
- La couleur porte une information ou n'est pas là. Palette et rôles : CDC §7.0.
- **Ne pas reprendre le vert/orange du livre AYEL & DAVIER dans les graphiques** :
  ce couple mesure ΔE 3,2 en vision protanope, il est indistinguable pour une partie
  des lecteurs. Le schéma du livre reste utilisable comme image sur la page d'aide.
- Format français : virgule décimale, espace insécable pour les milliers, taux à une décimale,
  temps affichés en `h min` mais toujours stockés et calculés en minutes.
- Jamais de double axe des ordonnées. Chaque graphique propose une vue tableau équivalente.

---

## Tests

`pytest -q` doit passer avant de considérer une tâche terminée. Les trente-sept invariants
du CDC §5.5 sont bloquants — en particulier :

- télescopage : `TQ × TP × DO == Tu / Tr` ;
- cas de référence : 30 ppm, To 840, Tr 570, quantité produite 13 200 → quantité produisible
  17 100, TRS 77,19 %, TRG 52,38 %, TRE 30,56 % ;
- bascule de cadence au 01/07/2026 : juin calculé à 24 ppm, juillet à 30 ppm, et modifier
  juillet ne touche pas juin ;
- non-régression du passé après modification de **chaque** table de référentiel ;
- union des intervalles d'arrêt (les cinq cas limites du CDC §4.6) ;
- neutralité de l'élément : changer l'élément d'un arrêt, déplacer un élément dans l'arbre
  ou retirer un équipement ne change aucun indicateur ;
- retrait non destructif d'un équipement ou d'un motif ; suppression protégée ;
- héritage de la liste de motifs le long de l'arborescence ;
- idempotence de l'import ;
- absence de facteur 60 (1 ppm, 300 paquets → Tn = 300 min) ;
- données manquantes distinguées d'une production nulle — jamais de TRS de 0 % pour un
  import oublié ;
- aucune fonction d'agrégation par article ne retourne de TRS.

Un test qui échoue n'est pas contourné en ajustant la valeur attendue.

---

## Dépôt et versions

Le dépôt Git sert aussi de vault Obsidian : `docs/` contient le journal de développement,
les décisions et les ressources. Dépôt **privé** sur GitHub, édité dans VSCode.

- **Ne jamais committer de données** : `data/trs.db`, extractions ERP, sauvegardes.
  Le `.gitignore` les couvre ; ne pas le contourner.
- **Seul le code est porté dans le dépôt** (règle 9). Le vault Obsidian — journal, décisions,
  cahier des charges détaillé — vit en dehors.
- **Une version = un tag Git** sur un état dont `pytest -q` passe, plus une entrée dans
  `CHANGELOG.md` rédigée pour un lecteur non développeur.
- **Toute décision structurante** donne lieu à une note dans `docs/Decisions/` : contexte,
  options, décision, conséquences, réversibilité.
- Messages de commit en français, à l'impératif, préfixés `socle:` `calcul:` `import:`
  `ui:` `test:` `docs:`. Le corps explique *pourquoi*, jamais *quoi*.

---

## Documentation

`docs/Notice_utilisateur.md` (CDC §12) est le pendant humain de ce fichier : mêmes règles,
formulées pour un utilisateur non développeur. Son chapitre 4 explique comment faire évoluer
l'application avec une IA.

**Les deux fichiers doivent rester cohérents.** Toute modification d'une règle ici impose de
relire la notice, et inversement. Une évolution qui change un comportement visible par
l'utilisateur n'est pas terminée tant que la notice ne le reflète pas.

Les chapitres 1 et 2 de la notice alimentent la page Aide de l'application : contenu écrit
une seule fois dans `docs/`, rendu par la page. Ne pas dupliquer le texte.

---

## Données, sauvegarde et confidentialité

- La base `data/trs.db` et les extractions ERP ne sont **jamais** versionnées (`.gitignore`).
- **`trs.db` ne doit jamais être placée dans le dossier SharePoint synchronisé** : le client
  de synchronisation peut la copier en cours d'écriture et la corrompre. La base reste locale ;
  seules des copies produites par `VACUUM INTO` partent vers SharePoint (CDC §13.7).
- Une sauvegarde qui échoue en silence est pire que pas de sauvegarde : toute écriture est
  journalisée, vérifiée après coup, et la date de la dernière réussite est affichée.
- Aucun appel réseau au fonctionnement de l'application.
- Pour développer sans l'extraction réelle : `generer_donnees_test.py`.

---

## Quand demander plutôt que décider

- Un choix qui modifierait des résultats déjà publiés.
- L'ajout d'un paramètre de calcul : il doit entrer dans `parametre_date` ou dans une table
  historisée, jamais en constante dans le code. En cas de doute, poser la question.
- Une simplification qui toucherait aux neuf règles ci-dessus.
- Une divergence entre le format réel de l'extraction ERP et ce que suppose le CDC §6.
- Une demande d'afficher un TRS par article, par équipe ou par personne — voir CDC §5.2 ter
  et §13.5.
- Un doute sur un terme, un exemple ou un jeu de test destiné au dépôt (règle 9).

Les questions ouvertes côté production sont listées au CDC §11 ; elles ne bloquent pas
le développement, le jeu de données fictives permet d'avancer sans elles.
