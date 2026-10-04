# Mucosal Vaccine Copilot — notice

**Da Vinci HackLab, Tours, 3–4 octobre 2026 — défi industriel Lovaltech**
Prototype réalisé en solo, sur littérature publique et données synthétiques.

---

## 1. Le problème, en une page

Vous voulez savoir si un vaccin nasal protège. Vous mesurez des anticorps.
Deux laboratoires vous rendent chacun un chiffre.

**Ces deux chiffres ne sont presque jamais sur la même échelle.**

Un exemple concret, et c'est le cœur du sujet :

- Le **lavage nasal** rince le nez avec du liquide. L'échantillon récupéré est
  **dilué**, d'un facteur important et surtout **variable d'un prélèvement à
  l'autre**.
- La **nasosorption** pose une petite bandelette absorbante contre la muqueuse.
  Elle recueille le fluide **tel quel**, sans dilution.

Le même patient, le même jour, la même quantité réelle d'anticorps : le lavage
donnera un nombre bien plus petit. Mettre ces deux nombres sur le même graphique
produit une courbe **fausse, et fausse de façon invisible** — rien, dans le
graphique, ne signale le problème au lecteur.

Même chose entre le **nez** et le **sang** : ce sont deux compartiments
immunitaires largement séparés. Un IgA nasal et un IgG sérique ne se comparent
pas, quelle que soit la qualité des deux mesures.

**Cet outil fait une seule chose, et il la fait de façon vérifiable : il dit si
deux mesures d'anticorps peuvent être comparées, et il refuse de les dessiner
ensemble quand elles ne le peuvent pas.**

---

## 2. Ce que l'outil sait faire

### a) Juger la comparabilité de deux mesures

Chaque mesure est décrite par **dix caractéristiques** : compartiment (nez,
salive, voies basses, sang), méthode de prélèvement, isotype d'anticorps, type
de dosage, unité, normalisation, antigène, laboratoire, seuil de quantification,
provenance.

Dix règles examinent ces caractéristiques et rendent un verdict :

| Verdict | Signification |
|---|---|
| **comparable** | même façon de produire les deux chiffres |
| **conditionnel** | comparable sous réserve — la réserve est écrite, avec le remède |
| **non comparable** | ne pas mettre sur le même axe |

**L'outil ne regarde jamais les valeurs mesurées.** Uniquement la façon dont
elles ont été produites. C'est ce qui lui permet de travailler même quand aucun
chiffre n'a été publié.

### b) Dessiner des cinétiques sans mentir

Un panneau par groupe comparable. Les séries non comparables **ne peuvent pas**
partager un axe absolu — ce n'est pas une consigne, c'est le code qui l'interdit.
La seule vue légitime entre compartiments est la **montée relative** de chaque
série par rapport à son propre point de départ.

Quand une série a moins de 4 temps de prélèvement distincts, l'outil **refuse
d'ajuster une courbe** et affiche les points seuls, en l'écrivant. Une courbe à
quatre paramètres passant par trois points s'ajuste toujours — et se trompe
toujours.

### c) Proposer un plan d'échantillonnage

Vous décrivez votre essai en français ou en anglais courant. L'outil propose des
jours de visite, en justifiant chaque option par une **citation littérale** d'un
article réel. Ce qu'il ne peut pas justifier est marqué **`ASSUMPTION`**, en
rouge.

Il refuse explicitement de trancher ce qui relève de l'expertise : le choix d'un
corrélat de protection, le dimensionnement de l'étude, l'acceptabilité d'un
dispositif. Ces questions sont listées comme « décisions d'expert requises ».

### d) Analyser des méthodes publiées

L'onglet **Consortia (Table 1)** applique le moteur à la Table 1 du rapport
d'atelier 2026 : six consortiums réels, leurs méthodes de prélèvement et leurs
dosages. Voir §5.

---

## 3. Ce que l'outil ne fait pas

- **Ce n'est pas un avis clinique, pas un protocole d'essai, pas un dispositif
  médical.** Il produit des *options candidates à la revue d'experts du domaine*.
- Il ne contient **aucune donnée patient** et **aucune donnée confidentielle**.
- Les mesures livrées avec l'outil sont **synthétiques** — fabriquées pour tester
  le moteur, pas pour décrire un vaccin réel. Les paramètres sont des hypothèses
  illustratives, pas des estimations.
- Sa base documentaire compte **7 études citables et 40 constats vérifiés**.
  C'est une amorce, pas une revue systématique.
- L'auteure est architecte logiciel et IA, **pas immunologiste**. Tout ce qui
  relève du jugement scientifique est remonté comme question ouverte, jamais
  tranché.

---

## 4. Ce que vous recevez

Un dépôt public, consultable et téléchargeable :

**https://github.com/corinne3/mucosal-vaccine-copilot**

Il contient :

| | |
|---|---|
| `RUN_ME_WINDOWS.txt` | **commencez par là** — installation pas à pas |
| `docker-compose.yml` | lance l'application en une commande |
| `app/` + `src/` | l'application et son moteur |
| `data/incoming/` | déposez-y vos propres fichiers CSV |
| `docs/POUR_LOVALTECH.md` | ce document |
| `docs/MANUEL_DASHBOARD.md` | manuel détaillé, écran par écran |
| `docs/STACK.md` | documentation technique complète |
| `docs/DOMAIN_PRIMER.md` | les notions d'immunologie mobilisées |
| `docs/LIMITS.md` | ce que l'outil ne fait pas, en détail |

Licence **MIT** : vous pouvez l'utiliser, le modifier et le redistribuer
librement. Les résumés d'articles cités restent la propriété de leurs éditeurs
et sont référencés par DOI ou PMID.

---

## 5. Le résultat que nous vous proposons de regarder en premier

Nous avons passé la **Table 1 de votre article** dans le moteur. Six
consortiums : COMMUNITY, GERMINATE, MOVE, MUSICC, Project NextGen, VAXXAIR.

Un consortium n'est pas une mesure. VAXXAIR prélève sur trois sites des voies
hautes, un site des voies basses, et fait deux familles de dosages ; et
« Humoral response (IgG/IgA titres) » décrit **deux** mesures dans une seule
case. Les six consortiums deviennent donc **38 contextes de mesure**.

Sur **561 paires inter-consortiums, aucune n'est pleinement comparable.**

- **547** sont écartées par une information que la Table 1 **contient** :
  compartiment, dispositif, isotype ou dosage différents.
- **14** s'accordent sur tout ce qui est publié. Pour celles-là, la réponse
  dépend entièrement de **cinq informations que la table ne contient pas**.

### Les cinq colonnes manquantes

| Information absente | Ce qu'elle décide |
|---|---|
| **unité** | si les deux nombres sont sur la même échelle. µg/mL et AU/mL ne se convertissent pas sans la calibration du dosage |
| **normalisation** | si la dilution du prélèvement a été annulée. Un IgA spécifique rapporté à l'IgA totale est comparable entre dispositifs ; brut, non |
| **seuil de quantification** | quelles valeurs sont des mesures et lesquelles sont des planchers. Sans lui, les points censurés passent pour réels |
| **antigène** | ce que l'anticorps reconnaît. Deux « titres IgA » contre des souches différentes répondent à des questions différentes |
| **laboratoire** | si un biais inter-sites est en jeu. Même dosage, site différent, facteur deux couramment |

**Ce n'est pas un reproche adressé aux consortiums**, et l'outil ne juge aucune
science : il ne voit que des métadonnées, et ces essais n'ont publié aucune
valeur. C'est une mesure de **ce qu'une table de méthodes, telle qu'elle s'écrit
aujourd'hui, permet à un lecteur de conclure** — et la liste des colonnes qu'un
standard de reporting harmonisé devrait ajouter.

### Et la bonne nouvelle, qui mérite d'être dite en premier

**Les six consortiums sur six utilisent déjà la nasosorption.**

Les dispositifs ont convergé. Le reporting, pas encore. C'est exactement l'écart
que cet outil mesure — et c'est un écart qu'on comble en ajoutant cinq colonnes,
pas en refaisant des essais.

---

## 6. Installation

### Ce qu'il vous faut

**Docker Desktop**, gratuit : https://www.docker.com/products/docker-desktop/

Rien d'autre. Pas besoin d'installer Python. Rien n'est ajouté à votre machine
en dehors de Docker, et désinstaller tient en une commande.

### Les étapes

**1.** Installez Docker Desktop, **lancez-le**, et attendez que son icône baleine
cesse de s'animer (indicateur vert, *Engine running*). C'est la cause n°1 des
échecs : la commande suivante ne marche pas tant que Docker Desktop n'est pas
démarré.

**2.** Téléchargez le projet : sur la page GitHub, bouton vert **Code** →
**Download ZIP**. Décompressez-le.

**3.** Ouvrez un terminal **dans ce dossier** (clic droit en maintenant Maj →
*Ouvrir une fenêtre PowerShell ici*), puis :

```
docker compose up
```

Le premier lancement télécharge et construit : comptez quelques minutes et
beaucoup de texte qui défile. C'est normal. Attendez la ligne :

```
You can now view your Streamlit app in your browser.
```

**4.** Ouvrez votre navigateur sur : **http://localhost:8501**

**Pour arrêter :** `Ctrl-C` dans le terminal, puis `docker compose down`.

### Si ça ne démarre pas

| Message | Cause | Solution |
|---|---|---|
| `docker: command not found` ou une erreur mentionnant `pipe` | Docker Desktop n'est pas lancé | lancez-le, attendez le vert, réessayez |
| `port is already allocated` | le port 8501 est pris | dans `docker-compose.yml`, remplacez le **premier** `8501` par `8601`, puis ouvrez `http://localhost:8601` |
| autre chose | | lancez `docker compose logs` et transmettez la sortie |

---

## 7. Utiliser vos propres mesures

Déposez un fichier CSV dans le dossier **`data/incoming`**, puis chargez-le
depuis la barre latérale de l'application.

Le dossier est monté **en lecture seule** : l'application lit votre fichier,
elle ne peut jamais le modifier ni l'effacer.

### Colonnes attendues

| Colonne | Signification | Exemple |
|---|---|---|
| `subject_id` | un participant | `P-001` |
| `day` | jour d'étude, 0 = référence | `14` |
| `value` | la valeur mesurée | `18.4` |
| `compartment` | où c'est mesuré | `nasal`, `oral`, `lower_airway`, `serum` |
| `method` | comment c'est prélevé | `nasosorption`, `nasal_wash`, `saliva`, `bal`, `serum` |
| `isotype` | quel anticorps | `IgA`, `sIgA`, `IgG`, `total` |
| `assay` | quel dosage | `elisa_binding`, `multiplex_binding`, `neutralization`, `hai` |
| `unit` | l'unité de `value` | `ug_ml`, `ng_ml`, `au_ml`, `titer`, `ratio` |
| `normalization` | par quoi c'est divisé | `none`, `total_iga`, `total_protein` |
| `lab` | quel laboratoire | `lab_A` |

**Les six dernières colonnes sont exactement celles qui décident de la
comparabilité.** En omettre une ne casse rien : l'outil met une valeur par
défaut et vous dit quels verdicts reposent sur ce défaut.

---

## 8. Deux points à connaître

**Les modèles d'IA sont optionnels.** La barre latérale affichera probablement
« Ollama service: not running ». C'est normal et sans conséquence : chaque
étape assistée par IA possède un repli déterministe, et l'application
fonctionne entièrement sans aucun modèle. Pour activer la recherche
sémantique dans la base documentaire : installez [Ollama](https://ollama.com)
puis `ollama pull nomic-embed-text`. Rien d'autre à configurer.

**Le réseau.** L'application écoute sur toutes les interfaces de la machine —
nécessaire dans un conteneur. Sur un réseau d'entreprise, vos collègues peuvent
donc y accéder depuis leur poste. Sans conséquence ici, puisque les données
livrées sont synthétiques ou publiques — mais à savoir **avant** d'y charger
un fichier de mesures réelles.

---

## 9. Contact

Corinne — GitHub [@corinne3](https://github.com/corinne3)

Les questions, demandes d'évolution et signalements de défauts peuvent être
déposés dans l'onglet *Issues* du dépôt.
