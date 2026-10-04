# Pitch 6 minutes — contenu des slides

**Da Vinci HackLab, Tours — défi Lovaltech.** Solo.

Minutage visé. Le temps indiqué est un **plafond** : finir à 5 min 30 est un
succès, dépasser est le seul échec irrattrapable d'un pitch de hackathon.

| # | Slide | Temps | Cumul |
|---|---|---|---|
| 1 | Titre | 15 s | 0:15 |
| 2 | Le problème | 50 s | 1:05 |
| 3 | Pourquoi c'est grave | 35 s | 1:40 |
| 4 | Ce que fait l'outil | 40 s | 2:20 |
| 5 | **Démo enregistrée** | 90 s | 3:50 |
| 6 | Le résultat sur vos données | 45 s | 4:35 |
| 7 | Comment c'est fait | 40 s | 5:15 |
| 8 | Ce que je refuse de faire | 25 s | 5:40 |
| 9 | Ce que vous repartez avec | 20 s | 6:00 |

---

## Slide 1 — Titre · 15 s

> # Mucosal Vaccine Copilot
> ### Deux chiffres d'anticorps ne sont comparables que s'ils ont été produits de la même façon.
>
> Défi Lovaltech — NoseAI_Guide · Corinne · solo
> github.com/corinne3/mucosal-vaccine-copilot

**À dire :** « Mon sujet tient en une phrase, celle qui est à l'écran. Je vais
vous montrer pourquoi c'est un problème, et ce que j'ai construit. »

---

## Slide 2 — Le problème · 50 s

Un visuel, deux colonnes :

| **Lavage nasal** | **Nasosorption** |
|---|---|
| on rince le nez avec du liquide | une bandelette absorbe le fluide |
| l'échantillon est **dilué** | **pas de dilution** |
| facteur important **et variable** | |

> **Même patient. Même jour. Même quantité réelle d'anticorps.**
> **Deux nombres qui n'ont rien à voir.**

**À dire :** « Voilà deux façons de prélever des anticorps dans le nez. La
première rince avec du liquide : ce qu'on récupère est dilué, d'un facteur
important, et surtout variable d'un prélèvement à l'autre. La seconde absorbe le
fluide tel quel. Même patient, même jour, même quantité réelle d'anticorps — et
deux nombres sans rapport. Ajoutez à ça que le nez et le sang sont deux
compartiments immunitaires séparés : un IgA nasal et un IgG sérique ne se
comparent pas, même parfaitement mesurés. »

---

## Slide 3 — Pourquoi c'est grave · 35 s

> ### Une courbe fausse, et fausse **de façon invisible**
>
> Rien dans le graphique ne prévient le lecteur.

Visuel : deux séries non comparables sur un même axe — l'allure est
parfaitement crédible. C'est tout l'argument.

**À dire :** « Si on met ces deux séries sur le même graphique, on obtient une
courbe fausse. Le problème n'est pas qu'elle soit fausse : c'est qu'elle est
crédible. Rien, dans la figure, ne permet au lecteur de s'en apercevoir. Et
comme il n'existe ni unité commune, ni normalisation imposée, ni standard de
reporting, chaque consortium publie dans son propre vocabulaire. »

---

## Slide 4 — Ce que fait l'outil · 40 s

> ### Dix caractéristiques par mesure → dix règles → trois verdicts
>
> compartiment · dispositif · isotype · dosage · unité · normalisation ·
> antigène · laboratoire · seuil · provenance
>
> → **comparable** / **conditionnel** / **non comparable**
>
> Chaque alerte porte **un code, un message, un remède.**
>
> ⚠️ **L'outil ne voit jamais les valeurs mesurées. Uniquement comment elles ont été produites.**

**À dire :** « Chaque mesure porte dix caractéristiques. Dix règles les
examinent et rendent un verdict, avec le remède à chaque fois. Le point
important est en bas : le moteur ne regarde jamais les valeurs. Uniquement la
façon dont elles ont été produites. C'est ce qui le rend testable — et c'est ce
qui lui permet de travailler là où aucun chiffre n'a été publié. »

---

## Slide 5 — Démo enregistrée · 90 s

**Une vidéo, muette, que tu commentes en direct.** Pas de live : le réseau ne
mérite pas ta confiance et 90 secondes ne pardonnent rien.

Trois plans, pas un de plus :

1. **(30 s)** Onglet *Comparability* — la matrice, et un verdict déplié qui
   montre son message et son remède.
2. **(30 s)** Onglet *Kinetics* — un panneau par groupe comparable, et la
   mention « too few to fit » sur une série à 3 points.
3. **(30 s)** Onglet *Consortia (Table 1)* — les trois chiffres, puis la table
   des cinq colonnes manquantes.

**À dire, sur le plan 2 :** « Les séries non comparables ne partagent pas un
axe. Ce n'est pas une consigne de bonne pratique, c'est le code qui l'interdit.
Et ici, l'outil refuse d'ajuster une courbe parce qu'il n'a que trois points de
mesure : une courbe à quatre paramètres passant par trois points s'ajuste
toujours, et se trompe toujours. »

> **Conseils d'enregistrement :** zoom navigateur à 125 %, curseur lent, aucune
> frappe au clavier — seulement des clics. Enregistre 3 fois, garde la
> meilleure. Mets la vidéo **dans** le support, pas dans un lecteur séparé.

---

## Slide 6 — Le résultat sur vos données · 45 s

**Le slide qui fait la différence. Il ne parle plus du prototype, il parle d'eux.**

> ### J'ai passé la Table 1 de votre article dans le moteur
>
> 6 consortiums → **38 contextes de mesure** → **561 paires**
>
> # Aucune n'est pleinement comparable.
>
> - **547** écartées par ce que la table **contient**
> - **14** décidées par **5 colonnes qu'elle ne contient pas** :
>   unité · normalisation · seuil · antigène · laboratoire
>
> ### ✅ Et : 6 consortiums sur 6 utilisent déjà la nasosorption.

**À dire :** « Je n'avais pas de données — j'ai utilisé la seule chose réelle
que j'avais : votre article. La Table 1 liste six consortiums et leurs méthodes.
Un consortium n'est pas une mesure : VAXXAIR prélève sur quatre sites et fait
deux familles de dosages, donc les six deviennent trente-huit contextes.
Cinq cent soixante et une paires, aucune pleinement comparable. Mais l'intérêt
est dans la répartition : 547 sont écartées par une information que la table
contient. Les 14 autres s'accordent sur tout ce qui est publié — pour
celles-là, la réponse dépend de cinq colonnes absentes. Ce n'est pas un reproche
aux consortiums : c'est une mesure de ce qu'une table de méthodes permet de
conclure aujourd'hui. Et la bonne nouvelle est en bas : les dispositifs ont déjà
convergé. C'est le reporting qui manque. »

---

## Slide 7 — Comment c'est fait · 40 s

> ### 5 584 lignes · **199 tests** · **8 métriques seuillées qui font échouer la CI**
>
> | | |
> |---|---|
> | Citation falsifiée détectée | **100 %** (144 cas) |
> | Vraie citation acceptée | **100 %** (40) |
> | Exactitude de comparabilité | **100 %** (13 paires étiquetées) |
>
> **Pas de GPU. Pas de cloud. Pas de clé d'API. Pas de LLM sur le chemin critique.**
> Chaque étape IA a un repli déterministe.

**À dire :** « Tout est mesuré, rien n'est déclaratif. La métrique dont je suis
la plus contente : la détection de citation falsifiée. J'avais un seuil de
similarité, et « did **not** induce » transformé en « did induce » scorait 0,95
— ça passait. Une négation inversée, c'est exactement là que l'hallucination se
cache. J'ai ajouté une condition sur le multiset des mots de contenu : on est
passé de 94 à 100 %. Et tout ça tourne sans GPU, sans cloud, sans clé d'API. »

**Si on te demande « et l'IA alors ? » :** « Les modèles sont optionnels,
partout, avec un repli déterministe. J'ai même mesuré le cas : sur une phrase
disant "3 visites", mon parseur à mots-clés lit 3 ; le modèle 3B répond 6 — la
valeur de l'exemple dans son propre prompt. Les règles ne peuvent pas halluciner
un nombre qu'elles n'ont pas vu. D'où l'architecture : règles sur le chemin
critique, modèle en option par-dessus. Il y a un écran dans l'outil qui fait
tourner les deux parseurs côte à côte, pour qu'on puisse vérifier plutôt que me
croire. »

---

## Slide 8 — Ce que je refuse de faire · 25 s

> ### L'outil refuse explicitement de trancher :
> - le choix d'un **corrélat de protection**
> - le **dimensionnement** de l'étude
> - l'**acceptabilité** d'un dispositif
>
> Ces questions sortent en « décisions d'expert requises ».
> Ce qui n'est pas justifié par une citation est marqué **`ASSUMPTION`**, en rouge.
>
> *Pas un avis clinique. Pas un protocole. Pas un dispositif médical.*
> *Je suis architecte logiciel, pas immunologiste.*

**À dire :** « Un mot sur ce que l'outil ne fait pas, parce que c'est une
décision de conception, pas une excuse. Il refuse de choisir un corrélat de
protection, de dimensionner une étude, de juger un dispositif. Ces questions
ressortent dans une liste intitulée "décisions d'expert requises". Et tout ce
qui n'est pas adossé à une citation littérale est marqué ASSUMPTION, en rouge.
Je suis architecte logiciel, pas immunologiste — et la limite principale du
projet, c'est qu'aucun immunologiste n'a encore relu mes dix règles. C'est la
première ligne de ma feuille de route. »

---

## Slide 9 — Ce que vous repartez avec · 20 s

> ### Disponible maintenant
> **github.com/corinne3/mucosal-vaccine-copilot** · licence MIT
>
> - `docker compose up` → l'application, sans installer Python
> - notice en français pour non-développeurs
> - vos CSV dans `data/incoming/` — monté **en lecture seule**
>
> ### Et un livrable qui ne demande aucun logiciel :
> # Les 5 colonnes à ajouter à une table de méthodes.

**À dire :** « Tout est en ligne, sous licence MIT, avec une notice écrite pour
quelqu'un qui n'a jamais ouvert un terminal — une commande et ça tourne. Mais
s'il ne devait rester qu'une chose de ces six minutes, ce serait la dernière
ligne : cinq colonnes à ajouter à une table de méthodes. Ça, ça ne demande
d'exécuter aucun logiciel. Merci. »

---

# Ce que j'ajouterais, et ce que je retirerais

**Tu as demandé si je voyais autre chose. Voici.**

### Le slide 6 est ton pitch

La structure classique — contexte / apport / comment / démo — ne prévoit pas de
case pour *« j'ai appliqué mon outil à vos propres données et voici le chiffre »*.
C'est pourtant ce qui te distingue de tout prototype de hackathon. **Si tu
manques de temps, coupe le slide 7, jamais le 6.**

### Ajoute le slide 8

Il n'est pas dans la structure classique et il devrait y être, surtout dans un
contexte santé. Un jury pharma écoute toute la journée des outils qui promettent
tout. **Dire ce qu'on refuse de faire est un signal de sérieux**, pas un aveu de
faiblesse — et ça désamorce à l'avance la question « est-ce que c'est validé ? ».

### Ne fais pas de slide « Équipe »

Tu es seule, le jury le sait. En revanche **place une phrase au slide 7** :

> « J'ai dirigé chez Atos un système de validation automatisée de cohérence sur
> des documents techniques ferroviaires. Là-bas, la question était de savoir si
> deux folios se contredisent. Ici, si deux mesures d'anticorps sont
> comparables. C'est la même machinerie. »

Ça transforme « projet de hackathon » en « compétence transférée », en douze
secondes.

### Ne fais pas de slide « Business model »

Pas sur un défi industriel, pas en six minutes. Si on te pose la question :
*« MIT, c'est un bien commun. La valeur n'est pas dans dix règles, elle est dans
le fait que quelqu'un les ait écrites explicitement et mesurées. Si suite il y
a, c'est du service — intégrer le moteur dans la chaîne de données d'un
consortium — pas de la licence. »*

### Ne montre pas d'architecture technique

Pas de diagramme de boîtes. En six minutes, un jury retient des **chiffres** et
une **phrase**. Les boîtes sont dans `docs/STACK.md` pour qui veut.

---

# Préparation

### Les trois phrases à savoir par cœur

1. *« Deux chiffres d'anticorps ne sont comparables que s'ils ont été produits de la même façon. »*
2. *« 561 paires, aucune pleinement comparable — et 14 qui ne dépendent que de cinq colonnes absentes. »*
3. *« Les dispositifs ont convergé. C'est le reporting qui manque. »*

### Les chiffres à ne pas confondre

| | |
|---|---|
| 38 | contextes de mesure |
| 561 | paires inter-consortiums |
| 14 | paires décidées par les métadonnées absentes |
| 5 | colonnes manquantes |
| 6/6 | consortiums utilisant la nasosorption |
| 199 | tests |

### Questions probables

**« C'est validé scientifiquement ? »**
> « Non, et c'est écrit partout dans le projet. Les règles sont traçables à des
> sources publiées, mais traçable n'est pas validé. Faire relire les dix règles
> par un immunologiste muqueux est la première ligne de ma feuille de route.
> L'outil est écrit pour rendre cette relecture facile : dix fonctions pures,
> lisibles séparément, avec leur justification à côté. »

**« Vos données sont synthétiques, quel intérêt ? »**
> « Les données synthétiques sont le banc d'essai, pas un bouche-trou. C'est le
> seul cadre où je connais la bonne réponse — je sais quel facteur de dilution
> j'ai injecté — donc le seul où je peux *prouver* que le moteur la trouve.
> C'est ce que mesure le 100 % de comparabilité. Et la Table 1, elle, est
> entièrement réelle : des métadonnées publiées, pas simulées. »

**« Pourquoi pas de LLM ? »**
> « Il y en a un, en option, à chaque étape — avec un repli déterministe partout.
> Ce que j'ai refusé, c'est de le mettre sur le chemin critique. Et je l'ai
> mesuré plutôt que supposé : sur une phrase disant "3 visites", mon parseur
> lit 3, le modèle 3B répond 6. Les règles ne peuvent pas halluciner un nombre
> qu'elles n'ont pas vu. Il y a un écran qui fait tourner les deux côte à côte. »

**« Vous étiez seule ? »**
> « Seule inscrite sur ce défi, et sans interlocuteur métier présent, sans
> données, avec un seul article. Ça a forcé une discipline qui est devenue la
> qualité principale du projet : tout ce qui n'est pas traçable est marqué comme
> non traçable. »

### Logistique

- Vidéo **intégrée au support**, pas dans un lecteur à part.
- Support en **PDF** sur clé USB *et* en pièce jointe envoyée à quelqu'un.
- Répète **chronomètre en main**, deux fois. Vise 5 min 30.
- Si tu perds le fil : saute directement au slide 6. C'est celui qui compte.
