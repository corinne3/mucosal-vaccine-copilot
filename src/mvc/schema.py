"""Objective 1 — Structured domain model.

Covers the four blocks asked by the brief:
  * trial design      -> Vaccine, Arm, TrialDesign
  * nasal sampling    -> SamplingMethod, SamplingEvent
  * immune endpoints  -> ImmuneEndpoint (compartment, isotype, assay, unit, normalisation)
  * kinetics          -> KineticParameters, Measurement

Design principle: every measured value carries its full *measurement context*
(compartment, sampling method, assay, unit, normalisation, lab...). Without that
context two numbers cannot be compared, and the comparability engine
(`mvc.comparability`) relies on it.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
class Route(str, Enum):
    intranasal = "intranasal"
    inhaled = "inhaled"
    intramuscular = "intramuscular"
    subcutaneous = "subcutaneous"
    oral = "oral"


class Platform(str, Enum):
    live_attenuated = "live_attenuated"
    adenovirus_vector = "adenovirus_vector"
    mrna = "mrna"
    inactivated = "inactivated"
    protein_subunit = "protein_subunit"
    other = "other"


class Compartment(str, Enum):
    """Where the immune response is measured."""

    nasal = "nasal"              # upper airway (URT) mucosa
    oral = "oral"                # saliva (mucosal, but NOT nasal)
    lower_airway = "lower_airway"  # LRT: BAL, bronchosorption, exhaled particles
    serum = "serum"              # systemic humoral
    blood_cells = "blood_cells"  # PBMC (ELISpot, flow cytometry)

    @property
    def is_mucosal(self) -> bool:
        return self in (Compartment.nasal, Compartment.oral, Compartment.lower_airway)


class SamplingMethod(str, Enum):
    nasal_wash = "nasal_wash"                    # lavage: large, variable dilution
    nasal_swab = "nasal_swab"                    # anterior nares swab
    nasal_mid_turbinate_swab = "nasal_mid_turbinate_swab"  # deeper than anterior nares
    nasopharyngeal_swab = "nasopharyngeal_swab"
    nasosorption = "nasosorption"                # synthetic absorptive matrix (SAM) strip
    nalt_biopsy = "nalt_biopsy"                  # nasal-associated lymphoid tissue, tissue not fluid
    tonsil = "tonsil"                            # tonsillar tissue
    saliva = "saliva"
    bal = "bal"                                  # bronchoalveolar lavage: dilutes, like nasal_wash
    bronchosorption = "bronchosorption"          # absorptive strip, lower airway
    pexa = "pexa"                                # particles in exhaled air
    serum = "serum"
    pbmc = "pbmc"


#: which sampling methods are physically possible in which compartment
METHOD_COMPARTMENT: dict[SamplingMethod, Compartment] = {
    SamplingMethod.nasal_wash: Compartment.nasal,
    SamplingMethod.nasal_swab: Compartment.nasal,
    SamplingMethod.nasal_mid_turbinate_swab: Compartment.nasal,
    SamplingMethod.nasopharyngeal_swab: Compartment.nasal,
    SamplingMethod.nasosorption: Compartment.nasal,
    SamplingMethod.nalt_biopsy: Compartment.nasal,
    SamplingMethod.tonsil: Compartment.nasal,
    SamplingMethod.saliva: Compartment.oral,
    SamplingMethod.bal: Compartment.lower_airway,
    SamplingMethod.bronchosorption: Compartment.lower_airway,
    SamplingMethod.pexa: Compartment.lower_airway,
    SamplingMethod.serum: Compartment.serum,
    SamplingMethod.pbmc: Compartment.blood_cells,
}


class Isotype(str, Enum):
    IgA = "IgA"
    sIgA = "sIgA"     # secretory IgA (dimeric + secretory component)
    IgG = "IgG"
    IgM = "IgM"
    total = "total"   # isotype-agnostic (e.g. neutralisation, HAI)
    na = "na"         # not applicable (cellular readouts)


class AssayType(str, Enum):
    elisa_binding = "elisa_binding"
    multiplex_binding = "multiplex_binding"   # MSD / Luminex
    neutralization = "neutralization"
    hai = "hai"                               # haemagglutination inhibition
    elispot = "elispot"
    flow_cytometry = "flow_cytometry"


class Normalization(str, Enum):
    none = "none"
    total_iga = "total_iga"          # specific IgA / total IgA
    total_protein = "total_protein"
    albumin = "albumin"
    urea = "urea"                    # dilution correction for lavage


class Unit(str, Enum):
    titer = "titer"                  # reciprocal dilution
    ng_ml = "ng_ml"
    ug_ml = "ug_ml"
    au_ml = "au_ml"                  # arbitrary units / mL (lab-specific!)
    bau_ml = "bau_ml"                # WHO binding antibody units
    od = "od"                        # optical density
    ratio = "ratio"                  # e.g. specific/total
    sfu_per_million = "sfu_per_million"
    percent = "percent"


#: unit groups that can be converted into each other with a fixed factor
UNIT_CONVERSIONS: dict[tuple[Unit, Unit], float] = {
    (Unit.ng_ml, Unit.ug_ml): 1e-3,
    (Unit.ug_ml, Unit.ng_ml): 1e3,
}


class EvidenceLevel(str, Enum):
    verified_abstract = "verified_abstract"   # statement checked against the published abstract
    verified_fulltext = "verified_fulltext"
    llm_extracted = "llm_extracted"           # extracted by a model, quote verified automatically
    extractive_auto = "extractive_auto"       # verbatim sentence selected by keyword rules (no LLM)
    expert_assumption = "expert_assumption"   # domain heuristic, no direct citation
    to_verify = "to_verify"


# --------------------------------------------------------------------------- #
# Trial design
# --------------------------------------------------------------------------- #
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Vaccine(_Base):
    name: str
    pathogen: str = Field(description="e.g. influenza, SARS-CoV-2, RSV")
    platform: Platform
    route: Route

    @property
    def is_mucosal_route(self) -> bool:
        return self.route in (Route.intranasal, Route.inhaled, Route.oral)


class Arm(_Base):
    arm_id: str
    vaccine: Vaccine
    dose_days: list[int] = Field(default_factory=lambda: [0], description="study days of each dose")
    n_participants: int = Field(ge=1)
    is_control: bool = False

    @field_validator("dose_days")
    @classmethod
    def _sorted_days(cls, v: list[int]) -> list[int]:
        if v != sorted(v):
            raise ValueError("dose_days must be sorted")
        return v


class Population(_Base):
    age_min: int = Field(ge=0, default=18)
    age_max: int = Field(ge=0, default=64)
    prior_immunity: str = Field(
        default="unknown",
        description="naive | low | high | unknown (pre-existing immunity from infection or vaccination)",
    )
    pediatric: bool = False

    @model_validator(mode="after")
    def _check_age(self) -> "Population":
        if self.age_min > self.age_max:
            raise ValueError("age_min > age_max")
        return self


class SamplingEvent(_Base):
    day: int = Field(description="study day relative to first dose (day 0)")
    method: SamplingMethod
    window_days: int = Field(default=0, ge=0, description="tolerated +/- window")

    @property
    def compartment(self) -> Compartment:
        return METHOD_COMPARTMENT[self.method]


class ImmuneEndpoint(_Base):
    endpoint_id: str
    label: str
    compartment: Compartment
    method: SamplingMethod
    isotype: Isotype
    assay: AssayType
    unit: Unit
    normalization: Normalization = Normalization.none
    antigen: str = "unspecified"
    primary: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> "ImmuneEndpoint":
        if METHOD_COMPARTMENT[self.method] != self.compartment:
            raise ValueError(
                f"sampling method {self.method.value} does not sample compartment {self.compartment.value}"
            )
        return self


class TrialDesign(_Base):
    trial_id: str
    title: str
    phase: str = "1"
    population: Population = Field(default_factory=Population)
    arms: list[Arm]
    sampling: list[SamplingEvent]
    endpoints: list[ImmuneEndpoint]
    follow_up_days: int = 180

    @model_validator(mode="after")
    def _endpoints_are_sampled(self) -> "TrialDesign":
        sampled = {s.method for s in self.sampling}
        missing = [e.endpoint_id for e in self.endpoints if e.method not in sampled]
        if missing:
            raise ValueError(f"endpoints without matching sampling events: {missing}")
        if any(s.day > self.follow_up_days for s in self.sampling):
            raise ValueError("sampling after end of follow-up")
        return self

    def sampling_days(self, method: SamplingMethod) -> list[int]:
        return sorted({s.day for s in self.sampling if s.method == method})


# --------------------------------------------------------------------------- #
# Kinetics & measurements
# --------------------------------------------------------------------------- #
class KineticParameters(_Base):
    """Summary of an antibody kinetic curve (see `mvc.kinetics`)."""

    baseline: float
    peak_value: float
    peak_day: float
    half_life_days: Optional[float] = None
    fold_rise: Optional[float] = None
    ci_peak_day: Optional[tuple[float, float]] = None
    ci_half_life: Optional[tuple[float, float]] = None
    n_subjects: int = 0
    n_timepoints: int = 0
    identifiable: bool = True
    notes: list[str] = Field(default_factory=list)


class MeasurementContext(_Base):
    """Everything needed to decide whether two values are comparable."""

    compartment: Compartment
    method: SamplingMethod
    isotype: Isotype
    assay: AssayType
    unit: Unit
    normalization: Normalization = Normalization.none
    antigen: str = "unspecified"
    lab: str = "lab_1"
    lloq: Optional[float] = Field(default=None, description="lower limit of quantification")
    source: str = Field(default="measured", description="measured | digitized_from_figure | synthetic")


class Measurement(_Base):
    subject_id: str
    arm_id: str
    day: float
    value: Optional[float]
    context: MeasurementContext
    below_lloq: bool = False


# --------------------------------------------------------------------------- #
# Input of objective 3: a trial *scenario* (what the user wants to run)
# --------------------------------------------------------------------------- #
class TrialScenario(_Base):
    name: str
    vaccine: Vaccine
    comparator: Optional[Vaccine] = None
    population: Population = Field(default_factory=Population)
    dose_days: list[int] = Field(default_factory=lambda: [0])
    n_participants: int = 30
    follow_up_days: int = 180
    max_visits: int = Field(default=6, ge=2, description="max sampling visits per participant")
    questions: list[str] = Field(
        default_factory=lambda: ["peak", "durability"],
        description="peak | durability | mucosal_vs_systemic | correlate_of_protection",
    )
    notes: str = ""


# --------------------------------------------------------------------------- #
# Evidence base (objective 2)
# --------------------------------------------------------------------------- #
class Finding(_Base):
    finding_id: str
    statement: str = Field(description="our normalised claim, in plain English")
    quote: str = Field(description="verbatim supporting text from the source")
    tags: list[str] = Field(default_factory=list)
    level: EvidenceLevel = EvidenceLevel.verified_abstract


class Study(_Base):
    study_id: str
    citation: str
    year: int
    doi: Optional[str] = None
    pmid: Optional[str] = None
    nct: Optional[str] = None
    url: Optional[str] = None
    pathogen: str
    vaccines: list[Vaccine] = Field(default_factory=list)
    population: str = "not reported"
    n_participants: Optional[int] = None
    sampling_methods: list[SamplingMethod] = Field(default_factory=list)
    compartments: list[Compartment] = Field(default_factory=list)
    timepoints_days: list[int] = Field(default_factory=list)
    assays: list[AssayType] = Field(default_factory=list)
    abstract: str = ""
    full_text_excerpts: str = Field(
        default="",
        description=(
            "Verbatim passages quoted from the body of the source, for studies whose useful "
            "content is not confined to the abstract. Kept separate from `abstract` so the "
            "stored abstract stays exactly that, while quote verification can still trace a "
            "body citation to text we actually hold."
        ),
    )
    findings: list[Finding] = Field(default_factory=list)
    not_reported: list[str] = Field(
        default_factory=list, description="fields that the source does not report (explicit gaps)"
    )
    level: EvidenceLevel = EvidenceLevel.verified_abstract

    @property
    def source_text(self) -> str:
        """Everything we hold verbatim from this source — the only thing a quote
        may be verified against. A quote that matches nothing here is not evidence."""
        return f"{self.abstract}\n\n{self.full_text_excerpts}".strip()


class EvidenceBase(_Base):
    version: str = "1"
    description: str = ""
    studies: list[Study]

    def by_id(self) -> dict[str, Study]:
        return {s.study_id: s for s in self.studies}


ALL_MODELS: list[type[BaseModel]] = [
    Vaccine, Arm, Population, SamplingEvent, ImmuneEndpoint, TrialDesign,
    KineticParameters, MeasurementContext, Measurement, TrialScenario,
    Finding, Study, EvidenceBase,
]
