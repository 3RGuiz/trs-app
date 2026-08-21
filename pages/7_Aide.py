"""Page d'aide : vocabulaire et lecture des indicateurs (CDC §7.8).

Le contenu est écrit une seule fois dans docs/Notice_utilisateur.md et rendu
ici : deux textes entretenus séparément divergeraient. Tant que la notice
n'existe pas, cette page porte le minimum vital pour éviter les contresens en
réunion.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui import commun

st.set_page_config(page_title="Aide", layout="wide")
st.title("Comprendre les indicateurs")

NOTICE = commun.RACINE / "docs" / "Notice_utilisateur.md"

if NOTICE.exists():
    contenu = NOTICE.read_text(encoding="utf-8")
    # Seuls les chapitres 1 et 2 alimentent cette page (CDC §12).
    debut = contenu.find("## Chapitre 1")
    fin = contenu.find("## Chapitre 3")
    st.markdown(contenu[debut:fin] if debut != -1 and fin != -1 else contenu)
    st.stop()

st.info(
    "La notice utilisateur complète sera rédigée en fin de développement. "
    "Cette page en reprendra alors les deux premiers chapitres."
)

st.subheader("Les temps, du plus large au plus utile")
st.markdown(
    """
| Temps | Ce qu'il représente | Exemple sur une journée |
|---|---|---|
| **Tt** — temps total | La durée calendaire, 24 h par jour | 1 440 min |
| **To** — temps d'ouverture | Le temps pendant lequel l'atelier est ouvert | 840 min (14 h) |
| **Tr** — temps requis | Le temps pendant lequel la ligne doit produire | 570 min (9 h 30) |
| **Tf** — temps de fonctionnement | Le temps requis moins les arrêts subis | 500 min |
| **Tn** — temps net | Le temps qu'il aurait fallu pour produire tout ce qui est sorti de la ligne | 450 min |
| **Tu** — temps utile | Le temps qu'il aurait fallu pour produire ce qui est bon | 440 min |

Entre To et Tr se trouvent les temps hors requis : pauses, nettoyage, démarrage
de ligne. Entre Tr et Tf, les arrêts subis. Entre Tf et Tn, la ligne a tourné
moins vite que sa cadence de référence. Entre Tn et Tu, la non-qualité.
"""
)

st.subheader("Les taux")
st.markdown(
    """
| Taux | Calcul | Ce qu'il dit |
|---|---|---|
| **TRS** | Tu / Tr | Ce que la ligne a produit rapporté à ce qu'elle aurait pu produire **pendant qu'elle devait tourner**. C'est l'indicateur de référence. |
| **TRG** | Tu / To | Même chose rapporté au temps d'ouverture : il intègre donc le niveau de charge. |
| **TRE** | Tu / Tt | Rapporté aux 24 heures de la journée. |
| **DO** — disponibilité | Tf / Tr | La part du temps requis pendant laquelle la ligne a effectivement tourné. |
| **TP** — performance | Tn / Tf | La vitesse tenue par rapport à la cadence de référence. |
| **TQ** — qualité | Tu / Tn | La part de la production qui est bonne. |
| **TC** — charge | Tr / To | La part du temps d'ouverture pendant laquelle la ligne devait produire. |
| **TS** — stratégique | To / Tt | La part de la journée pendant laquelle l'atelier est ouvert. |

Le TRS est le produit des trois premiers : **TRS = TQ × TP × DO**.
"""
)

st.subheader("Exemple chiffré, à vérifier à la calculatrice")
st.markdown(
    """
Cadence de référence 30 UVC par minute, temps requis 9 h 30, soit 570 minutes.

- Quantité produisible : 30 × 570 = **17 100 UVC**
- Quantité réellement produite : **13 200 UVC**
- TRS = 13 200 / 17 100 = **77,2 %**

C'est la même chose que Tu / Tr : 13 200 / 30 = 440 minutes de temps utile,
et 440 / 570 = 77,2 %. Les deux lectures donnent toujours le même résultat.
"""
)

st.subheader("Trois erreurs de lecture fréquentes")
st.markdown(
    """
**« Le TRS a baissé, la ligne va moins bien. »** Pas nécessairement. Si la cadence
de référence a été relevée entre les deux périodes, la barre a monté et le TRS
baisse mécaniquement. L'application signale ces dates et propose une lecture à
cadence constante, qui montre le progrès réel.

**« La moyenne des TRS de la semaine. »** Une moyenne de taux est fausse dès que
les journées n'ont pas la même durée de production. L'application additionne
toujours les temps, puis calcule le taux — jamais l'inverse.

**« Le TRS de cet article. »** Il n'existe pas ici. Le temps utile se ventile par
article, le temps requis non : l'ERP ne dit pas combien de temps a été passé sur
chaque ordre de fabrication. Par article, l'application affiche le taux de
réalisation et la quantité produite.
"""
)

st.subheader("Quand un indicateur affiche « non mesuré »")
st.markdown(
    """
Ce n'est pas une panne, c'est une donnée qui manque. Tant qu'aucun arrêt n'est
saisi, la disponibilité et la performance ne peuvent pas être séparées ; tant
qu'il n'existe pas de compteur en sortie d'ensacheuse, la non-qualité et l'écart
de cadence restent mélangés.

Le TRS, lui, reste **exact** dans tous les cas : ces données servent à le
décomposer, pas à le calculer. Afficher « 100 % » à la place de « non mesuré »
serait un mensonge par omission.
"""
)
