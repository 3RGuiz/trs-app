# Journal des versions

Écrit pour un lecteur non développeur : ce qui change **pour l'utilisateur**.
Version la plus récente en haut. Chaque version correspond à un tag Git posé sur un état
dont les tests passent.

---

## v0.2 — 21/08/2026 — Écrans d'analyse et de saisie

### Nouveautés

- Sept écrans : accueil, import, référentiel, rendement, TRS, paramètres,
  arrêts et aide. L'application se pilote entièrement depuis l'interface.
- **Import guidé** : choix du fichier, association des colonnes mémorisée d'un
  import à l'autre, aperçu des différences avant écriture, rapport détaillé.
- **Référentiel** : cadences, calendrier, familles, motifs, composition de la
  ligne et paramètres de calcul, tous datés. Chaque changement demande une date
  d'effet et un motif écrit, consultables dans le journal des modifications.
- **Écran TRS** : cascade des temps, évolution, origine des arrêts par motif,
  par zone ou par équipement, et comparaison de deux périodes.
- **Comparaison à cadence constante** : quand la cadence de référence change,
  le TRS baisse mécaniquement sans qu'aucune performance n'ait reculé. Les deux
  lectures sont affichées côte à côte pour montrer le progrès réel.
- **Saisie des arrêts** avec création de motif sans quitter l'écran, recherche
  de libellés proches, et contrôle du cumul par rapport au temps disponible.
- Chaque graphique propose une vue tableau équivalente.

### À savoir avant de mettre à jour

- L'application n'écoute plus que sur le poste local et n'envoie plus aucune
  statistique d'usage.
- L'export Excel des résultats et la notice utilisateur restent à produire.

---

## v0.1 — 21/08/2026 — Socle, moteur de calcul et import

### Nouveautés

- L'application calcule le TRS, le TRG et le TRE d'une ligne à partir des
  quantités produites, sans aucune saisie d'arrêts (niveau 1 du cahier des
  charges). Les indicateurs non mesurables affichent « non mesuré », jamais 100 %.
- Tous les référentiels (cadences, calendrier, motifs, familles...) sont datés :
  modifier une valeur ne change jamais les résultats du passé, et chaque
  modification exige un commentaire, conservé au journal.
- Import des extractions ERP au format Excel ou CSV, avec aperçu des différences
  avant toute écriture, sauvegarde automatique préalable et bouton d'annulation.
  Réimporter deux fois le même fichier ne crée aucun doublon.
- Sauvegarde de la base par copie cohérente, avec vérification après écriture
  et rotation des copies.
- Un générateur de données fictives (`python generer_donnees_test.py`) permet
  d'essayer l'application sans données réelles.
- Page d'accueil : indicateurs de la période, fraîcheur des données, alertes.

### À savoir avant de mettre à jour

- Première version fonctionnelle : les écrans de saisie des arrêts, du
  référentiel et l'assistant de premier lancement restent à construire.
- 80 tests automatiques couvrent les invariants de calcul du cahier des charges.

---

## v0.0 — 21/08/2026 — Mise en place

Dépôt initialisé. Aucun code fonctionnel.

---

<!--
Modèle pour les versions suivantes :

## vX.Y — JJ/MM/AAAA — Titre court

### Nouveautés
-

### Corrections
-

### À savoir avant de mettre à jour
- (par exemple : une sauvegarde de la base est recommandée)
-->
