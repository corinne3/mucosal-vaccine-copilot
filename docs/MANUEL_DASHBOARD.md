# Manuel du dashboard — ce que tu vois, et ce qui tourne derrière

Pour chaque contrôle et chaque onglet : ce que ça fait, **quel code s'exécute**, ce que tu
dois observer, et comment le casser pour comprendre.

Lancement :

```powershell
python -m mvc.cli dashboard
```

Ça exécute `streamlit run app/dashboard.py` (voir `src/mvc/cli.py`, fonction `cmd_dashboard`).

---

## 0. Le modèle mental à avoir d'abord

**Streamlit ré-exécute le script entier, de haut en bas, à chaque interaction.**

Tu bouges un curseur → tout `app/dashboard.py` repart de la ligne 1. Il n'y a pas
d'« événement bouton » comme dans une interface classique : le script tourne, et
`st.button(...)` renvoie `True` seulement pendant la ré-exécution qui suit le clic.

C'est contre-intuitif, et ça explique tout le reste du fichier :

```python
@st.cache_data(show_spinner=False)
def _data(n: int, seed: int) -> pd.DataFrame:
    return demo_dataset(n=n, seed=seed)
```

Sans ce cache, les 2220 lignes de données seraient **régénérées à chaque clic**. Avec, elles
ne sont recalculées que si `n` ou `seed` changent.

Quatre caches dans le fichier :

| Cache | Ce qu'il garde | Recalculé quand |
|---|---|---|
| `_evidence()` | la base de preuves | jamais (entrée fixe) |
| `_searcher()` | le moteur de recherche **et ses embeddings** | jamais — d'où `cache_resource` |
| `_data(n, seed)` | le tableau de mesures | si tu bouges « Participants » ou « Seed » |
| `_agent(text)` | le résultat complet de l'agent | si tu changes le texte du scénario |

`cache_resource` au lieu de `cache_data` pour le moteur de recherche : c'est un objet lourd
et non sérialisable (il contient une matrice d'embeddings). `cache_data` essaierait de le
copier, `cache_resource` le partage tel quel.

---

## 1. L'adaptateur Streamlit, tout en haut du fichier

Avant toute chose, le fichier fait ceci :

```python
for _name in ("plotly_chart", "dataframe"):
    _fn = getattr(st, _name)
    if not _accepts(_fn, "use_container_width") and _accepts(_fn, "width"):
        setattr(st, _name, _shim_container_width(_fn))
```

**Pourquoi.** Streamlit étirait un graphique à la largeur de sa colonne avec
`use_container_width=True`. Les versions récentes prennent `width="stretch"` et ont retiré
l'ancien mot-clé. Le dashboard appelle ça **11 fois** — si le mauvais mot-clé est passé, les
11 plantent.

Plutôt que de deviner quelle version tu as, le code **inspecte la signature** une fois et ne
traduit que si nécessaire. Les 11 sites d'appel restent écrits à l'ancienne : il n'y a rien
à garder synchronisé.

C'est un patron utile à connaître : quand tu ne peux pas tester une dépendance, adapte-toi
**au point d'entrée**, pas à chaque usage.

---

## 2. La barre latérale, contrôle par contrôle

### « Dataset » : Synthetic demo / Upload CSV

```python
source = st.radio("Dataset", ["Synthetic demo", "Upload CSV"], index=0)
...
if uploaded is not None:
    df = pd.read_csv(uploaded)
else:
    df = _data(n, int(seed))
```

- **Synthetic demo** → `src/mvc/synthetic.py`, fonction `demo_dataset()`. Les données sont
  **fabriquées**, pas lues.
- **Upload CSV** → c'est ici qu'un vrai fichier de laboratoire prendrait la place du
  synthétique, sans changer une ligne du reste.

Juste après, une **validation stricte** :

```python
required = {"subject_id", "day", "value", "compartment", "method", "isotype", "assay", "unit"}
missing = required - set(df.columns)
if missing:
    st.error(f"Missing columns: {sorted(missing)}")
    st.stop()
```

8 colonnes obligatoires. Sans elles, le moteur de comparabilité ne peut rien dire — donc le
dashboard **refuse de continuer** plutôt que d'afficher quelque chose de faux.

6 colonnes optionnelles reçoivent une valeur par défaut (`normalization="none"`,
`lab="lab_1"`, `source="measured"`…).

> **Pour tester :** fais un CSV avec seulement `subject_id,day,value` et charge-le. Tu dois
> voir le message d'erreur listant les 5 colonnes manquantes, et rien d'autre.

### « Participants per arm » (10 → 80, pas de 5)

Passe à `demo_dataset(n=...)`. Le nombre de lignes est
`2 bras × n sujets × 37 jours cumulés`. À n=30 → 2220 lignes ; à n=80 → 5920.

**Effet visible :** plus de sujets → intervalles de confiance plus **étroits** sur l'onglet
Kinetics. C'est la statistique qui se voit à l'œil.

### « Seed » (graine aléatoire)

Passe à `demo_dataset(seed=...)`. Change **toutes** les valeurs, puisqu'elles sont tirées au
hasard.

> **La démonstration la plus parlante de la session** : change la graine et regarde le
> tableau « Fitted parameters ». Le jour du pic bouge. **C'est honnête** : avec 30 sujets,
> l'estimation est variable — et c'est précisément pour ça que l'intervalle de confiance
> existe. Si tu veux montrer une seule chose sur l'incertitude dimanche, montre ça.

### « Bootstrap resamples » (50 / 100 / 150 / 300)

Passe à `fit_kinetics(n_boot=...)` dans `src/mvc/kinetics.py`.

Le bootstrap **ré-échantillonne les sujets** (pas les lignes), refait l'ajustement, et prend
les percentiles. 150 tirages = 150 ajustements de courbe par série.

**C'est le seul vrai réglage de performance.** À 300, l'onglet Kinetics devient nettement
plus lent. À 50, les bandes sont visiblement plus irrégulières.

**Pourquoi par sujet et pas par ligne :** les mesures répétées sur une même personne sont
corrélées. Ré-échantillonner les lignes les traiterait comme indépendantes et **sous-estimerait**
l'incertitude — exactement l'erreur qu'un outil sur l'incertitude ne doit pas commettre.

### « Log y axis »

Passe à `kinetics_figure(log_y=...)`. Les titres d'anticorps couvrent des ordres de grandeur
(10 à 640 pour les titres, 6 à 400 pour le sérum). En échelle linéaire, les petites valeurs
s'écrasent.

> Décoche-la une fois pour voir pourquoi elle est cochée par défaut.

### « Auto-convert compatible units »

```python
if harmonize:
    df = harmonize_units(df)
```

`src/mvc/comparability.py`, fonction `harmonize_units`. Convertit **uniquement** les paires
dont le facteur est fixe : ng/mL ↔ µg/mL (×1000).

Les unités arbitraires (`au_ml`) **n'apparaissent dans aucune paire de conversion**, exprès :
elles sont définies par la courbe d'étalonnage d'un labo, les convertir serait de la fiction.

> **À tester :** décoche-la, va dans Comparability. Le couple de séries sérum ng_ml / ug_ml
> passe de `conditional` (convertible) à... reste `conditional` — la règle les détecte comme
> convertibles de toute façon. Ce que tu changes, c'est si la **conversion est appliquée aux
> valeurs** avant le tracé.

### Le bloc « Local LLM »

```python
st.write(f"Ollama: {'reachable' if llm.is_available() else 'not reachable'}")
st.caption(f"Retrieval: {_searcher().mode}")
```

Affiche honnêtement ce dont l'outil dispose. Chez toi : **« hybrid (BM25 + embeddings) »**,
parce que tu as téléchargé `nomic-embed-text`. Sans lui : « BM25 only ».

**La capacité est déclarée, jamais masquée.** C'est un principe du projet : l'outil dit ce
qu'il peut faire.

---

## 3. Onglet **Scenario** — texte libre → plan de prélèvement

### Ce qui se passe au clic

```python
if st.button("Propose a candidate plan", type="primary"):
    with st.spinner("Running the agent…"):
        proposal, critique, log, parser, retrieved, report = _agent(text)
```

`_agent(text)` appelle `run_agent` dans `src/mvc/strategy/agent.py`, qui enchaîne :

```
parse → propose → retrieve → critique ─┬→ report
           ▲                           │
           └──── revise (1 fois max) ──┘
```

| Nœud | Fichier | Ce qu'il fait |
|---|---|---|
| `parse` | `agent.py::parse_scenario_rules` | ta phrase → objet `TrialScenario`, par mots-clés |
| `propose` | `strategy/rules.py::propose` | les 11 règles produisent les options |
| | `strategy/optimal_design.py::optimal_days` | D-optimalité pour les visites restantes |
| `retrieve` | `evidence/search.py` | cherche des preuves pour chaque question ouverte |
| `critique` | `agent.py::critique` | 7 contrôles objectifs |
| `revise` | `agent.py::node_revise` | une seule réparation mécanique |

### Les 4 métriques en haut

| Métrique | D'où elle vient |
|---|---|
| **Visits** | `len(proposal.sampling_days)` |
| **Options** | `proposal.coverage["options"]` |
| **Evidence-backed** | `coverage["evidence_backed"]` — **calculé**, pas déclaré : `len(evidence) > 0` |
| **Self-check** | `critique.passed` — les 7 contrôles |

### Les options dépliables

```python
icon = "⚠️" if o.assumption else "✅"
with st.expander(f"{icon} {o.option_id} · {o.choice}", expanded=o.assumption):
```

Note le `expanded=o.assumption` : **les options sans preuve s'ouvrent automatiquement.** Tu
ne peux pas les rater. Les options sourcées restent repliées.

- ✅ → affiche la citation **verbatim** et le DOI
- ⚠️ → affiche un avertissement : « unverified assumption »

### « Agent trace and self-check »

Déplie-le. Tu vois la trace nœud par nœud, et le JSON des 7 contrôles.

> **À tester, c'est la plus belle démo** : remplace le texte par
> `"intranasal covid vaccine, 3 visits, 90 days, durability"`. L'agent va **échouer** son
> auto-contrôle (3 visites ne peuvent pas répondre à une question de durabilité), **réparer
> une fois**, et la trace te montre les 8 étapes.

---

## 4. Onglet **Kinetics** — l'onglet le plus dense

### Le graphique du haut : plusieurs panneaux, pas un seul

```python
st.plotly_chart(kinetics_figure(df, n_boot=n_boot, log_y=log_y), ...)
```

`src/mvc/figures.py::kinetics_figure`. Et la ligne qui compte :

```python
groups = split_comparable_groups(df)
```

Cette fonction **groupe les séries en demandant au moteur de comparabilité** si elles peuvent
partager un axe. Chaque groupe devient un panneau.

**La mise en page porte le verdict.** Tu ne peux pas superposer deux séries non comparables,
parce qu'elles ne sont pas dans le même panneau.

Dans chaque panneau :
- **points** = médiane par jour
- **ligne** = courbe de Bateman ajustée
- **bande claire** = intervalle de confiance à 95 % par bootstrap
- **trait vertical pointillé** = jour du pic estimé
- **couleur** = compartiment · **style de trait** = dispositif de prélèvement

Et sur un panneau : **des points, aucune courbe**, avec la note
*« fit not identifiable — points only »*. C'est la série à 3 points de temps. 4 paramètres,
3 points → l'outil **refuse**.

### Le graphique du bas : fold-rise

`figures.py::fold_rise_figure`. **Le seul axe partagé légitime.**

```
fold_rise = valeur / valeur du jour 0 du MÊME sujet, DANS LA MÊME SÉRIE
```

Le « dans la même série » est important : un sujet contribue à 6 séries. Diviser une valeur
sérique par une ligne de base nasale serait exactement l'erreur que le projet combat.

Deux lignes de repère : **1** (ligne de base) et **4** (seuil conventionnel de 4-fold),
celle-ci étiquetée *« confirm with the expert »* — elle est affichée, pas affirmée.

### Le tableau « Fitted parameters »

Une ligne par (bras × compartiment × méthode × unité), via `fit_kinetics`.

Regarde deux colonnes :
- **`identifiable`** → `False` sur au moins une ligne
- **`notes`** → les auto-diagnostics : *« Half-life poorly constrained »*,
  *« Peak day uncertain (95% CI wider than 3 weeks) »*

> Ces notes ne sont pas décoratives : elles **génèrent des tâches** dans l'onglet Roadmap.

---

## 5. Onglet **Comparability** — le cœur

### Les 3 compteurs

```python
mat, details = comparability_matrix(df)
bad  = [... if r.label == "not_comparable"]
cond = [... if r.label == "conditional"]
```

`src/mvc/comparability.py::comparability_matrix` compare **toutes les paires**. Avec 6 séries,
ça fait 15 paires. Tu dois voir environ **14 paires non comparables**.

### La heatmap

Vert = comparable · orange = conditionnel · rouge = non comparable.
La diagonale est toujours verte (une série est comparable à elle-même — vérifié par test).

### La section « Why » — la plus importante

Chaque paire problématique est dépliable et contient la sortie de
`comparability.py::explain` :

```
Verdict: not_comparable
- [not_comparable] SAMPLING_METHOD : dispositifs nasaux différents sans
  normalisation commune — les facteurs de dilution diffèrent.
  → Normaliser l'IgA spécifique sur l'IgA totale avant de comparer.
```

**Chaque drapeau porte un code, un message et un remède.** Un expert peut contester *une
règle précise*, pas « le modèle ».

> **L'exercice qui ancre tout** : dans `src/mvc/comparability.py`, commente le corps de la
> règle `different_compartment`. Relance. Les panneaux nasal et sérum **fusionnent** dans
> l'onglet Kinetics, et tu vois de tes yeux le graphique trompeur que l'outil existe pour
> empêcher. Puis `git checkout src/mvc/comparability.py`.

---

## 6. Onglet **Uncertainty** — qualité des données

`comparability.py::audit_table` note chaque série sur quatre défauts :

| Défaut détecté | Seuil |
|---|---|
| trop peu de points de temps | < 4 |
| valeurs sous le seuil de quantification | > 20 % |
| valeurs manquantes | > 15 % |
| pas de ligne de base au jour 0 | — |
| unités arbitraires | — |

Couleur : vert = low, orange = medium, rouge = high (≥ 2 défauts).

La légende du bas avoue un raccourci : les valeurs censurées sont imputées à LLOQ/2, ce qui
**biaise les moyennes vers le bas**. C'est assumé et c'est une tâche de la roadmap.

---

## 7. Onglet **Evidence** — la base documentaire

### La recherche

```python
for h in _searcher().search(q, k=6, citable_only=citable_only):
    st.markdown(f"**`{h.chunk.chunk_id}`** · score {h.score:.4f} · ranks {h.ranks}")
```

Regarde `ranks` dans l'affichage : `{'bm25': 1, 'dense': 3}` te dit **quel moteur a trouvé
quoi, et à quelle place**. C'est la fusion RRF rendue visible.

La case « Citable sources only » filtre sur `chunk.citable` — les 4 études « à vérifier »
disparaissent.

> **À essayer :** cherche `"why can results not be compared across different trials"`. C'est
> la requête centrale du projet, celle qui scorait **zéro** avant l'ajout de la racinisation.

### Le graphe de connaissances

`evidence/graph.py::build_graph` → 121 nœuds, 240 arêtes. Couleur par type : étude, finding,
tag, méthode, compartiment, plateforme.

### « Coverage gaps »

`graph.py::coverage_gaps` → les combinaisons plateforme × méthode que **aucune** étude ne
couvre.

**Savoir où la preuve est absente vaut autant que savoir où elle est.** C'est la fonction qui
deviendra centrale quand on encodera la Table 1.

---

## 8. Onglet **Roadmap**

`roadmap.py::build_roadmap(state, df)`. Rien n'est écrit à la main : chaque tâche vient d'un
manque détecté, et porte son **origine**.

| Manque | Tâche générée |
|---|---|
| option sans preuve | « Valider ou rejeter : … » |
| question ouverte | « Trancher : … » avec propriétaire assigné par mots-clés |
| étude non vérifiée | « Récupérer et vérifier N placeholders » |
| paires non comparables | « Réduire les N paires » |
| série trop pauvre | « Ajouter des points de temps » |

Et la section PI énonce **des faits et des questions, jamais de conseil** — la stratégie PI
est l'affaire d'un juriste.

---

## 9. Onglet **Quality** — les évaluations

Clique « Run evals » → `eval/run.py::run_all(fast=True)`.

8 métriques de contrôle + 2 informatives. Détail complet dans la conversation et dans
`docs/objectifs/`.

Deux à retenir :
- **`extraction_fake_detection`** — seuil exactement `1.00`. Une seule fuite = échec.
- **`retrieval_mrr`** — 0,971 chez toi en hybride contre 0,843 en lexical seul.

`fast=True` réduit le nombre de répétitions pour que l'interface reste réactive.

---

## 10. Les trois choses à montrer dimanche, dans l'ordre

**1. Le problème (30 s)** — Onglet Comparability. Deux séries d'IgA nasale, mêmes
participants, dispositifs différents. Déplie une paire rouge : le remède est écrit.

**2. Le refus (30 s)** — Onglet Kinetics. *« Regardez : plusieurs panneaux, pas un seul. Le
moteur interdit l'axe commun. »* Puis montre les points sans courbe : *« 3 points de temps,
l'outil refuse d'ajuster. »*

**3. La comparaison légitime (30 s)** — Le graphique fold-rise, juste en dessous. La réponse
muqueuse du bras nasal est visible, celle du bras injecté non, et l'axe est honnête.

**La phrase de fin :** *« Le livrable n'est pas le graphique, c'est le refus de tracer le
mauvais graphique. »*

---

## 11. Ce que ce dashboard n'est pas

- Les données affichées sont **synthétiques**. Chaque ligne porte `source="synthetic"`, et
  une règle interdit de les mélanger à du mesuré.
- Les graphiques ne disent **rien de vrai sur un vaccin**. Ils montrent que le code sait
  tracer, et surtout refuser de tracer.
- Ce n'est **pas un avis clinique**. Voir `docs/LIMITS.md`.

---

## 12. Si quelque chose casse

Streamlit affiche l'erreur dans la page **et** dans le terminal. Garde la traceback complète.

| Symptôme | Cause probable |
|---|---|
| onglet Kinetics vide ou en erreur | `figures.py`, probablement `add_vline` ou `add_annotation` avec `row=`/`col=` |
| erreur sur `fillna` ou `replace` | pandas 3.0, plus récent que ce qui a été simulé |
| tout est étiré bizarrement | l'adaptateur Streamlit s'est trompé de sens |
| « Missing columns » | ton CSV n'a pas les 8 colonnes obligatoires |

Pour repartir propre : `git checkout app/ src/`.
