# Impact & Innovation Canvas — Mucosal Vaccine Copilot

**Da Vinci HackLab, Tours, octobre 2026 — défi industriel Lovaltech (NoseAI_Guide)**
Projet solo. Littérature publique et données synthétiques uniquement.

> Format texte volontaire. Chaque rubrique est renseignée avec ce qui a
> réellement été construit et mesuré ; là où je n'ai pas de réponse, je l'écris
> au lieu de remplir la case.

---

## 1. Problème

Le développement des vaccins muqueux est freiné par une raison moins visible
que la biologie : **on ne sait pas comparer les mesures entre essais.**

Trois faits, tirés du rapport d'atelier 2026 fourni par Lovaltech :

- Les anticorps muqueux se mesurent par des dispositifs aux comportements
  physiques différents. Le lavage nasal **dilue** d'un facteur important et
  variable ; la nasosorption **ne dilue pas**. Le même patient donne deux
  nombres très différents.
- Muqueuse et sang sont des compartiments **séparés**. Un IgA nasal et un IgG
  sérique ne se comparent pas, même parfaitement mesurés.
- Il n'existe ni unité commune, ni normalisation imposée, ni standard de
  reporting. Chaque consortium publie ses méthodes dans son propre vocabulaire.

**Conséquence opérationnelle :** mettre deux séries non comparables sur un même
graphique produit une courbe fausse — et fausse **de façon indétectable pour le
lecteur**. Rien dans la figure ne signale le problème.

**Qui en souffre :** les consortiums qui veulent mutualiser leurs résultats, les
industriels qui doivent choisir un critère d'évaluation, les régulateurs qui
doivent lire des dossiers hétérogènes.

---

## 2. Bénéficiaires

| Qui | Ce qu'ils en retirent |
|---|---|
| **Lovaltech** | un outil opérationnel + la liste précise des métadonnées à exiger de leurs partenaires |
| **Consortiums d'essais** (6 identifiés dans la Table 1) | savoir à l'avance quelles comparaisons inter-essais seront possibles — avant de prélever |
| **Équipes cliniques** | un plan d'échantillonnage justifié par citation, et la liste explicite des décisions qui leur reviennent |
| **Lecteurs et évaluateurs** | des figures qui ne peuvent pas juxtaposer l'incomparable |

**Bénéficiaire final, indirect :** le patient — un corrélat de protection muqueux
identifié plus vite, c'est un vaccin nasal évalué plus vite.

---

## 3. Solution

Un moteur de règles qui tranche la comparabilité de deux mesures d'anticorps,
**à partir des seules métadonnées**, et qui interdit structurellement de
dessiner ensemble ce qui ne peut pas l'être.

Trois niveaux de verdict — `comparable` / `conditionnel` / `non comparable` — et
chaque alerte porte **un code, un message et un remède**.

Autour de ce noyau :

- une base documentaire où **chaque recommandation cite une phrase littérale**
  d'un article réel, vérifiée automatiquement ;
- un agent qui propose un plan d'échantillonnage, **se critique**, se corrige une
  fois, et **refuse explicitement** de trancher ce qui relève de l'expert ;
- un tableau de bord où chaque onglet déclare ce qu'il lit et ce qu'il ignore.

---

## 4. Ce qui est innovant

Je distingue ce qui est nouveau de ce qui est simplement bien fait.

**Réellement innovant — le déplacement de la contrainte dans le type.**
La comparabilité n'est pas un avertissement en bas de figure : c'est une
propriété du modèle de données. La couche graphique est *incapable* de tracer
deux séries non comparables sur un axe absolu partagé. On ne peut pas oublier
d'appliquer la règle, parce qu'il n'y a pas de chemin de code qui la contourne.

**Réellement innovant — mesurer une table de méthodes publiée.**
À ma connaissance, personne n'a fait tourner un moteur de comparabilité sur les
méthodes publiées d'essais en cours pour **quantifier** ce que le reporting
permet de conclure. Le résultat est un chiffre vérifiable — 14 paires sur 561 —
et une liste de cinq colonnes manquantes. C'est le passage d'une critique
qualitative (« il faudrait harmoniser ») à une mesure actionnable.

**Innovant dans l'usage — la vérification de citation par multiset.**
Similarité de caractères ≥ 0.97 **et** multiset de mots de contenu identique.
La deuxième condition existe parce que « did **not** induce » → « did induce »
score 0.95 et passait un seuil à 0.92. Une négation inversée, c'est là que
l'hallucination se cache réellement. Détection : 94 % → **100 %**.

**Bien fait, mais pas nouveau :** BM25, la fusion RRF, le design D-optimal
bayésien, le bootstrap. Ce sont des techniques établies. Leur mérite ici est
d'être **implémentées lisiblement et évaluées**, pas d'être inédites.

**Contre-courant assumé :** aucun LLM sur le chemin critique. À l'heure où la
réponse par défaut est « un agent et un RAG », ce projet mesure que son parseur
à mots-clés **bat** un modèle 3B sur la lecture d'un nombre explicite — et en
tire une architecture plutôt qu'un slogan.

---

## 5. Faisabilité — ce qui est démontré

Tout est construit, exécuté et mesuré. Rien de ce qui suit n'est une intention.

| | |
|---|---|
| Code | 5 584 lignes, 26 modules |
| Tests | **199**, dont plusieurs gardant une transcription, pas du code |
| Évaluation | **8 métriques seuillées** qui font échouer la CI |
| Base documentaire | 11 études, 7 citables, 40 constats à citation vérifiée |
| Cas réel | 6 consortiums → 38 contextes → 561 paires |
| Livraison | conteneur Docker testé de bout en bout |
| Intégration continue | lint, tests, évals, démo, intégrité des preuves, sur Python 3.10 et 3.12 |

Quelques métriques :

- détection de citation falsifiée : **100 %** sur 144 citations corrompues
- acceptation des vraies citations : **100 %** sur 40
- exactitude de comparabilité : **100 %** sur 13 paires étiquetées
- couverture des intervalles de confiance : **8/8**

**Contrainte matérielle :** tout a été conçu pour tourner sur un PC **sans GPU,
sans crédit d'API, sans réseau garanti**. Chaque étape assistée par IA possède
un repli déterministe. C'est une contrainte qui a amélioré l'architecture.

---

## 6. Impact

### Court terme — Lovaltech, immédiat

Cinq colonnes nommées à ajouter à une table de méthodes, et les 14 paires
précises où cet ajout changerait la réponse. **Coût pour eux : documenter, pas
re-prélever.**

### Moyen terme — les consortiums

Un essai qui sait **avant de prélever** quelles comparaisons seront possibles
choisit ses dispositifs en conséquence. L'outil déplace la question de
l'analyse (trop tard) vers la conception (encore réversible).

Signal encourageant déjà mesuré : **6 consortiums sur 6 utilisent la
nasosorption**. La convergence des dispositifs est faite ; c'est le reporting
qui manque.

### Long terme — la contribution réelle serait un standard

L'outil ne vaut pas par son code. Il vaut parce qu'il produit un **argument
chiffré** en faveur d'un jeu minimal de métadonnées obligatoires. Si ces cinq
colonnes deviennent une pratique, l'outil aura servi même si personne ne
l'exécute jamais.

### Impact environnemental et sociétal

- **Sobriété numérique :** pas de GPU, pas d'appel cloud, pas de ré-entraînement.
  L'exécution complète tient sur un portable. Le modèle optionnel le plus lourd
  pèse 2 Go et reste optionnel.
- **Souveraineté des données :** rien ne sort de la machine. Aucune clé d'API,
  aucun service tiers. Un laboratoire pharmaceutique peut l'exécuter sur des
  données non publiées sans accord de transfert.
- **Accessibilité :** MIT, conteneur en une commande, notice écrite pour
  non-développeurs.

---

## 7. Modèle de valeur

**Ce projet n'est pas un produit, et je ne prétends pas le contraire.**

- **Licence MIT.** Le code est un bien commun. La valeur n'est pas dans
  l'algorithme — dix règles, quelques centaines de lignes — mais dans le fait
  que **quelqu'un les ait écrites explicitement et mesurées**.
- **Pas de propriété intellectuelle revendiquée** sur les règles : elles
  dérivent de connaissances publiées. Le projet inclut une feuille de route PI
  qui sépare les **faits** des **questions pour un conseil juridique**, sans les
  confondre.
- **Modèle plausible, si suite il y a :** service, pas licence. Intégrer le
  moteur dans la chaîne de données d'un consortium, encoder son vocabulaire
  propre, maintenir la base documentaire. Le code reste ouvert ; le travail
  d'intégration est le service.

---

## 8. Risques et limites — assumés

| Risque | Gravité | Ce qui est fait |
|---|---|---|
| **Les données de mesure sont synthétiques** | élevée en apparence | c'est le **banc d'essai** : seul cadre où la bonne réponse est connue, donc seul cadre où l'on peut *prouver* que le moteur la trouve. La Table 1 apporte, elle, des métadonnées réelles |
| **Base documentaire de 7 études citables** | moyenne | amorce assumée, écrite dans le README. Les 4 études non vérifiées sont marquées non citables et refusées |
| **Je ne suis pas immunologiste** | élevée | tout jugement de domaine est remonté comme question ouverte. L'outil refuse de choisir un corrélat de protection, de dimensionner une étude, de juger un dispositif |
| **Le prior cinétique du design D-optimal est une hypothèse** | moyenne | écrit dans la sortie elle-même, à chaque exécution |
| **Un utilisateur pourrait prendre les sorties pour un protocole** | élevée | mention « non clinique » en tête de chaque écran, formulation « options candidates à la revue d'experts », `docs/LIMITS.md` |
| **Le projet n'a pas été relu par un expert du domaine** | **élevée, non mitigée** | c'est la limite principale. Aucun immunologiste n'a validé les règles. Elles sont traçables à des sources publiées, mais traçable n'est pas validé |

**Ce que je ne sais pas :** si les dix règles sont les bonnes dix. Elles sont
défendables et sourcées, mais seul un comité du domaine peut le trancher — et
l'outil est écrit pour rendre ce verdict facile à rendre : les règles sont
dix fonctions pures, lisibles séparément, avec leur justification à côté.

---

## 9. Suite — horizon 90 jours

Généré par l'outil lui-même, à partir des lacunes de sa propre exécution
(`mvc/roadmap.py`, 20 tâches) :

1. **Faire relire les dix règles** par un immunologiste muqueux. Priorité
   absolue : c'est la limite non mitigée du §8.
2. **Porter la base documentaire de 7 à ~30 études citables**, en conservant
   la vérification de citation automatique comme garde-fou.
3. **Confronter l'outil à de vraies mesures.** Le moteur n'a jamais vu de
   données réelles. Un jeu de données réel, même petit, même ancien.
4. **Proposer les cinq colonnes** comme contribution à un standard de reporting.
5. **Étiqueter davantage de paires de comparabilité** — 13 paires, c'est peu
   pour une métrique à 100 %.

---

## 10. Équipe

Solo. Seule participante sur ce défi.

**Corinne** — architecte logiciel et IA. A conçu et dirigé chez Atos un système
de **validation automatisée de cohérence** sur des documents techniques
ferroviaires hétérogènes pour la SNCF.

**C'est le même problème, transposé.** Là-bas, la question était de savoir si
deux folios se contredisent. Ici, si deux mesures d'anticorps sont comparables.
La machinerie est identique : rendre le contexte explicite, rendre les règles
lisibles, refuser de fusionner ce qui ne peut pas l'être, et ne jamais affirmer
ce qu'on ne peut pas tracer.

**Ce que le hackathon a changé :** le défi n'a fourni aucune donnée, un seul
article, et aucun interlocuteur métier présent. Travailler sans expert du
domaine disponible a forcé une discipline qui est devenue la qualité principale
du projet — **tout ce qui n'est pas traçable est marqué comme non traçable.**
