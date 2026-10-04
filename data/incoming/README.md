# Put your own measurement CSVs here

Any CSV placed in this folder is visible to the app running in the container,
at `data/incoming/`. The container mounts it **read-only** — it can read your
file, it can never change or delete it.

Expected columns (the app tells you which are missing if any are):

| column | meaning | example |
|---|---|---|
| `subject_id` | one participant | `P-001` |
| `day` | study day, 0 = baseline | `14` |
| `value` | the measured number | `18.4` |
| `compartment` | where it was measured | `nasal`, `oral`, `lower_airway`, `serum` |
| `method` | how it was sampled | `nasosorption`, `nasal_wash`, `saliva`, `bal`, `serum` |
| `isotype` | which antibody | `IgA`, `sIgA`, `IgG`, `total` |
| `assay` | which test | `elisa_binding`, `multiplex_binding`, `neutralization`, `hai` |
| `unit` | the unit of `value` | `ug_ml`, `ng_ml`, `au_ml`, `titer`, `ratio` |
| `normalization` | what it was divided by | `none`, `total_iga`, `total_protein` |
| `lab` | which laboratory produced it | `lab_A` |

The last six columns are the ones that decide whether two numbers may be
compared. Leaving one out does not break the app — it fills in a default and
tells you which verdicts rest on that default.
