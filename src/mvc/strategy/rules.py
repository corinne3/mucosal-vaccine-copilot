"""Objective 3 — scenario -> *candidate* sampling & endpoint options.

SCOPE AND LIMITS (read this first)
---------------------------------
This module does NOT give clinical advice and does not design real trials.
It is a traceability engine. Given a scenario, it assembles a set of candidate
measurement choices and, for each one, shows:

  * what the choice is,
  * why it was proposed (a short engineering rationale),
  * which verified literature findings are attached to it (verbatim quotes),
  * whether it rests on evidence at all, or only on an unsupported assumption.

Every output is a *question for the domain experts* (immunologist, clinical
trial expert, biostatistician), never a conclusion. The value of the tool is
that nothing is silently assumed: `assumption=True` marks each option the
evidence base does not actually support.

Design: small pure functions registered in RULES, each appending to a mutable
`Plan`. Easy to read, easy to unit-test, easy to extend during a hackathon.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..evidence.store import CITABLE
from ..schema import (
    Arm,
    AssayType,
    Compartment,
    EvidenceBase,
    ImmuneEndpoint,
    Isotype,
    Normalization,
    Route,
    SamplingEvent,
    SamplingMethod,
    TrialDesign,
    TrialScenario,
    Unit,
)

DISCLAIMER = (
    "Engineering prototype on public and synthetic data. Candidate measurement options "
    "for review by qualified domain experts. Not clinical advice, not a trial protocol."
)


class EvidenceRef(BaseModel):
    study_id: str
    finding_id: str
    citation: str
    quote: str
    url: str | None = None


class Option(BaseModel):
    """One candidate choice, with its full provenance."""

    option_id: str
    category: str  # endpoint | sampling_method | timepoints | analysis | open_question
    choice: str
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumption: bool = False
    expert_review: str = Field(
        default="", description="what the domain expert must confirm or reject"
    )
    rule: str = ""

    @property
    def support(self) -> str:
        return "unsupported assumption" if self.assumption else f"{len(self.evidence)} verified finding(s)"


class StrategyProposal(BaseModel):
    disclaimer: str = DISCLAIMER
    scenario: TrialScenario
    endpoints: list[ImmuneEndpoint]
    sampling_days: list[int]
    sampling_methods: list[SamplingMethod]
    options: list[Option]
    open_questions: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    candidate_days: list[int] = Field(default_factory=list)
    design_notes: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> dict:
        n = len(self.options)
        supported = sum(1 for o in self.options if not o.assumption)
        return {
            "options": n,
            "evidence_backed": supported,
            "assumptions": n - supported,
            "share_backed": round(supported / n, 2) if n else 0.0,
        }

    def to_trial_design(self) -> TrialDesign:
        """Materialise the options as a `TrialDesign` object (a data structure to
        hand to the experts, not an approved protocol)."""
        scn = self.scenario
        arms = [Arm(arm_id="A", vaccine=scn.vaccine, dose_days=scn.dose_days,
                    n_participants=scn.n_participants)]
        if scn.comparator:
            arms.append(Arm(arm_id="B", vaccine=scn.comparator, dose_days=scn.dose_days,
                            n_participants=scn.n_participants, is_control=True))
        sampling = [
            SamplingEvent(day=d, method=m, window_days=0 if d < 7 else (1 if d < 30 else 3))
            for d in self.sampling_days
            for m in self.sampling_methods
        ]
        return TrialDesign(trial_id=f"candidate-{scn.name}", title=scn.name,
                           population=scn.population, arms=arms, sampling=sampling,
                           endpoints=self.endpoints, follow_up_days=scn.follow_up_days)


@dataclass
class Plan:
    """Mutable draft shared across rules."""

    endpoints: list[ImmuneEndpoint] = field(default_factory=list)
    methods: set[SamplingMethod] = field(default_factory=set)
    mandatory_days: set[int] = field(default_factory=set)
    options: list[Option] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


class EvidenceResolver:
    """Resolves finding ids to verbatim quotes, refusing non-citable sources."""

    def __init__(self, eb: EvidenceBase):
        self.index: dict[str, tuple] = {}
        for s in eb.studies:
            for f in s.findings:
                self.index[f.finding_id] = (s, f)

    def refs(self, finding_ids: list[str]) -> list[EvidenceRef]:
        out = []
        for fid in finding_ids:
            hit = self.index.get(fid)
            if not hit:
                continue
            s, f = hit
            if s.level in CITABLE and f.level in CITABLE:
                out.append(EvidenceRef(study_id=s.study_id, finding_id=fid,
                                       citation=s.citation, quote=f.quote, url=s.url))
        return out

    def option(self, plan: Plan, option_id: str, category: str, choice: str, rationale: str,
               finding_ids: list[str], expert_review: str, rule_name: str) -> None:
        ev = self.refs(finding_ids)
        opt = Option(option_id=option_id, category=category, choice=choice, rationale=rationale,
                     evidence=ev, assumption=not ev, expert_review=expert_review, rule=rule_name)
        plan.options.append(opt)
        plan.trace.append(f"{rule_name} -> {option_id} [{opt.support}]")


Rule = Callable[[TrialScenario, Plan, EvidenceResolver], None]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def is_mucosal_route(scn: TrialScenario) -> bool:
    return scn.vaccine.route in (Route.intranasal, Route.inhaled, Route.oral)


def functional_assay(scn: TrialScenario) -> AssayType:
    return AssayType.hai if scn.vaccine.pathogen.lower().startswith("influenza") else AssayType.neutralization


# --------------------------------------------------------------------------- #
# Rules: each proposes ONE candidate and names what the expert must settle
# --------------------------------------------------------------------------- #
@rule
def r_sampling_devices(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    plan.methods |= {SamplingMethod.serum, SamplingMethod.nasosorption}
    ev.option(
        plan, "O-DEVICE", "sampling_method",
        "Candidate: one single nasal device for the whole trial (nasosorption proposed), plus paired serum",
        "Engineering constraint, not a clinical one: the comparability engine flags any two mucosal "
        "series collected with different devices and no shared normalisation, so mixing devices "
        "fragments the dataset.",
        [],
        "Which device is acceptable for this population and this site's lab workflow?",
        "r_sampling_devices",
    )
    plan.open_questions.append(
        "Device choice (nasosorption / lavage / swab) and its recovery efficiency: expert decision."
    )


@rule
def r_paired_compartments(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    ev.option(
        plan, "O-PAIRED", "sampling_method",
        "Candidate: sample nasal and serum compartments at the same visits (paired)",
        "Paired sampling is what makes a within-subject mucosal-vs-systemic comparison possible at all; "
        "unpaired visits make the dashboard's compartment comparison uninterpretable.",
        ["bean2024_f2", "thwaites2023_f1"],
        "Is paired sampling feasible given visit burden?",
        "r_paired_compartments",
    )


@rule
def r_endpoint_candidates(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    nasal_method = next((m for m in sorted(plan.methods, key=lambda x: x.value)
                         if m != SamplingMethod.serum), SamplingMethod.nasosorption)
    pathogen = scn.vaccine.pathogen
    fa = functional_assay(scn)
    plan.endpoints += [
        ImmuneEndpoint(
            endpoint_id="nasal_siga", label="Nasal antigen-specific sIgA, normalised to total IgA",
            compartment=Compartment.nasal, method=nasal_method, isotype=Isotype.sIgA,
            assay=AssayType.elisa_binding, unit=Unit.ratio, normalization=Normalization.total_iga,
            antigen=pathogen, primary=is_mucosal_route(scn),
        ),
        ImmuneEndpoint(
            endpoint_id="serum_igg", label="Serum antigen-specific IgG (binding)",
            compartment=Compartment.serum, method=SamplingMethod.serum, isotype=Isotype.IgG,
            assay=AssayType.elisa_binding, unit=Unit.bau_ml, antigen=pathogen,
            primary=not is_mucosal_route(scn),
        ),
        ImmuneEndpoint(
            endpoint_id=f"serum_{fa.value}", label=f"Serum functional antibodies ({fa.value})",
            compartment=Compartment.serum, method=SamplingMethod.serum, isotype=Isotype.total,
            assay=fa, unit=Unit.titer, antigen=pathogen,
        ),
    ]
    if is_mucosal_route(scn):
        ev.option(
            plan, "O-EP", "endpoint",
            "Candidate: carry a mucosal endpoint alongside the systemic ones (not systemic only)",
            "The literature in the evidence base reports that mucosal and blood antibody responses are "
            "induced separately and correlate weakly, so one compartment cannot stand in for the other "
            "in the analysis.",
            ["thwaites2023_f1", "thwaites2023_f4", "bean2024_f2"],
            "Which endpoint is primary, and is the mucosal assay validated at this lab?",
            "r_endpoint_candidates",
        )
    else:
        ev.option(
            plan, "O-EP", "endpoint",
            "Candidate: systemic endpoints primary; mucosal endpoint exploratory",
            "For an injected comparator the evidence base reports little or inconsistent mucosal IgA, "
            "so a mucosal primary endpoint would likely be underpowered.",
            ["tsunetsugu2022_f2", "sheikhmohamed2022_f1"],
            "Keep the mucosal endpoint as exploratory, or drop it?",
            "r_endpoint_candidates",
        )
    plan.open_questions.append("Primary vs secondary endpoint ranking: expert and regulatory decision.")


@rule
def r_normalisation(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    ev.option(
        plan, "O-NORM", "analysis",
        "Candidate: report nasal specific IgA both raw and normalised to total IgA",
        "Data-engineering rationale: mucosal sample dilution varies between visits, so the raw value "
        "mixes biology with sampling. Keeping both lets the reviewer see the effect of normalisation "
        "instead of trusting it.",
        [],
        "Is total-IgA normalisation the accepted practice for this assay?",
        "r_normalisation",
    )


@rule
def r_baseline_and_prior_immunity(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    plan.mandatory_days.add(0)
    ev.option(
        plan, "O-BASELINE", "timepoints",
        "Candidate: baseline (day 0) sample in every compartment, before any dose",
        "Without a day-0 value, fold-rise over own baseline cannot be computed, and fold-rise is the only "
        "scale on which the dashboard can compare compartments at all.",
        ["bean2024_f3", "tsunetsugu2022_f3", "singh2023_f3"],
        "How will pre-existing immunity be measured and handled in the analysis?",
        "r_baseline_and_prior_immunity",
    )
    if scn.population.prior_immunity in ("unknown", "high"):
        plan.open_questions.append(
            "Prior immunity is unknown or high: the evidence base reports it can raise baselines and mask "
            "between-arm differences. Stratification is an expert and statistical decision."
        )


@rule
def r_post_dose_windows(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    """Candidate windows derive from the *reported* timepoints in the evidence base,
    not from an assumed biology: see `evidence_timepoints`."""
    for d in scn.dose_days:
        plan.mandatory_days.add(d + 7)
        if scn.follow_up_days >= d + 28:
            plan.mandatory_days.add(d + 28)
    ev.option(
        plan, "O-WINDOW", "timepoints",
        f"Candidate anchor visits around each dose: day+7 and day+28 (doses at {scn.dose_days})",
        "These are the windows most frequently reported in the evidence base for mucosal and systemic "
        "readouts; they are anchors to discuss, and the optimal-design module then fills the remaining "
        "visit budget to minimise parameter uncertainty.",
        ["tsunetsugu2022_f1", "singh2023_f1", "sheikhmohamed2022_f4", "thwaites2023_f3"],
        "Are these windows compatible with the clinical schedule and the assay turnaround?",
        "r_post_dose_windows",
    )


@rule
def r_durability_visit(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    if "durability" not in scn.questions:
        return
    late = min(180, scn.follow_up_days)
    plan.mandatory_days.add(late)
    ev.option(
        plan, "O-DURABILITY", "timepoints",
        f"Candidate late visit at day {late} for the durability question",
        "The half-life of a kinetic fit is unidentifiable without a late sample: without it the model "
        "extrapolates beyond the data and `mvc.kinetics` flags the estimate as poorly constrained.",
        ["sheikhmohamed2022_f2"],
        "Is retention at this timepoint realistic?",
        "r_durability_visit",
    )


@rule
def r_responder_rate_and_size(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    ev.option(
        plan, "O-RESPONDER", "analysis",
        "Candidate: pre-specify a responder definition and report the responder fraction per timepoint",
        "The evidence base contains intranasal studies where the mucosal response was inconsistent across "
        "participants. A mean over responders and non-responders hides that, so the fraction is reported "
        "separately rather than averaged away.",
        ["madhavan2022_f1", "sheikhmohamed2022_f1"],
        "What is the responder definition, and what sample size does it imply? (biostatistician)",
        "r_responder_rate_and_size",
    )
    plan.open_questions.append("Sample size and power: biostatistician decision, out of scope for this tool.")


@rule
def r_assay_standardisation(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    ev.option(
        plan, "O-ASSAY", "analysis",
        "Candidate: one reference standard and one lab per assay, or bridging samples if split",
        "The comparability engine marks arbitrary units and cross-lab series as not comparable, so this is "
        "the condition under which the dataset stays analysable as a whole.",
        ["tsunetsugu2022_f4"],
        "Which reference standard is available for this antigen?",
        "r_assay_standardisation",
    )


@rule
def r_cellular_optional(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    if "correlate_of_protection" not in scn.questions:
        return
    plan.methods.add(SamplingMethod.pbmc)
    plan.endpoints.append(ImmuneEndpoint(
        endpoint_id="iga_asc", label="IgA-secreting plasmablasts (ELISpot)",
        compartment=Compartment.blood_cells, method=SamplingMethod.pbmc, isotype=Isotype.IgA,
        assay=AssayType.elispot, unit=Unit.sfu_per_million, antigen=scn.vaccine.pathogen,
    ))
    ev.option(
        plan, "O-CELL", "endpoint",
        "Candidate exploratory endpoint: blood IgA-secreting plasmablasts",
        "A blood draw is cheaper and better standardised than mucosal sampling; the evidence base reports "
        "this marker being used after intranasal vaccination.",
        ["singh2023_f4", "thwaites2023_f3"],
        "Is ELISpot capacity available, and at which visit?",
        "r_cellular_optional",
    )
    plan.open_questions.append(
        "No accepted correlate of protection exists for mucosal influenza vaccines in this evidence base; "
        "any correlate claim is out of scope for this prototype."
    )


@rule
def r_uncertainty_disclosure(scn: TrialScenario, plan: Plan, ev: EvidenceResolver) -> None:
    ev.option(
        plan, "O-UNCERTAINTY", "open_question",
        "Candidate: ship the uncertainty with the numbers (bootstrap CIs, LLOQ censoring, comparability flags)",
        "Required by the brief and by honesty: the dashboard refuses to put non-comparable series on one "
        "absolute axis and labels every fit it cannot constrain.",
        ["bean2024_f4", "thwaites2023_f5"],
        "Which caveats must appear in the expert-facing report?",
        "r_uncertainty_disclosure",
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def evidence_timepoints(eb: EvidenceBase, max_day: int = 365) -> list[int]:
    """Timepoints actually reported by the citable studies — the empirical prior
    behind the candidate windows above."""
    days: set[int] = set()
    for s in eb.studies:
        if s.level in CITABLE:
            days |= {d for d in s.timepoints_days if 0 <= d <= max_day}
    return sorted(days)


def propose(
    scn: TrialScenario,
    eb: EvidenceBase,
    use_optimal_design: bool = True,
    seed: int = 0,
) -> StrategyProposal:
    """Run every rule, then fill the remaining visit budget by D-optimal design."""
    plan = Plan()
    resolver = EvidenceResolver(eb)
    for r in RULES:
        r(scn, plan, resolver)

    mandatory = sorted(d for d in plan.mandatory_days if 0 <= d <= scn.follow_up_days)
    candidates = sorted(set(mandatory) | set(evidence_timepoints(eb, scn.follow_up_days)))
    design_notes: list[str] = []

    if len(mandatory) >= scn.max_visits:
        days = mandatory[: scn.max_visits]
        design_notes.append(
            f"Visit budget ({scn.max_visits}) is already filled by the anchor visits; "
            "the optimal-design step was skipped and visits were truncated."
        )
        if len(mandatory) > scn.max_visits:
            plan.open_questions.append(
                f"Dropped anchor visits {mandatory[scn.max_visits:]} to respect the visit budget: "
                "which question is the team willing to give up?"
            )
    elif use_optimal_design:
        from .optimal_design import CANDIDATE_DAYS, optimal_days

        res = optimal_days(
            scn,
            mandatory=mandatory,
            candidates=sorted(set(candidates) | {d for d in CANDIDATE_DAYS if d <= scn.follow_up_days}),
            seed=seed,
        )
        days = res.days
        candidates = res.candidate_days
        added = [d for d in days if d not in mandatory]
        design_notes.append(
            f"Bayesian D-optimal design added {added} to the anchor visits {mandatory} "
            f"(kinetic prior: {res.profile}; log det FIM = {res.criterion:.2f})."
        )
        design_notes.append(
            "The prior is an illustrative assumption, not a fitted estimate: the chosen days are only as "
            "good as that prior, which is why they are presented as a proposal."
        )
    else:
        days = mandatory

    return StrategyProposal(
        scenario=scn,
        endpoints=plan.endpoints,
        sampling_days=sorted(set(days)),
        sampling_methods=sorted(plan.methods, key=lambda m: m.value),
        options=plan.options,
        open_questions=plan.open_questions,
        trace=plan.trace,
        candidate_days=candidates,
        design_notes=design_notes,
    )


def to_markdown(p: StrategyProposal) -> str:
    """Expert-facing briefing: every option with its support and its open question."""
    cov = p.coverage
    lines = [
        f"# Candidate measurement plan — {p.scenario.name}",
        "",
        f"> {p.disclaimer}",
        "",
        f"**Vaccine** {p.scenario.vaccine.name} ({p.scenario.vaccine.route.value}, "
        f"{p.scenario.vaccine.platform.value}) · **n** {p.scenario.n_participants} · "
        f"**follow-up** {p.scenario.follow_up_days} d · **visit budget** {p.scenario.max_visits}",
        "",
        f"**Proposed visits:** {', '.join('D' + str(d) for d in p.sampling_days)}",
        f"**Sampling:** {', '.join(m.value for m in p.sampling_methods)}",
        "",
        f"**Evidence coverage:** {cov['evidence_backed']}/{cov['options']} options carry verified findings "
        f"({cov['assumptions']} rest on unsupported assumptions).",
        "",
        "## Candidate options",
        "",
    ]
    for o in p.options:
        tag = "ASSUMPTION — no supporting evidence" if o.assumption else f"{len(o.evidence)} verified finding(s)"
        lines += [f"### {o.option_id} · {o.category} — *{tag}*", "", f"**{o.choice}**", "", o.rationale, ""]
        for e in o.evidence:
            lines.append(f"- {e.citation}")
            lines.append(f"  > \"{e.quote}\"")
        if o.expert_review:
            lines += ["", f"**For the expert:** {o.expert_review}"]
        lines.append("")
    if p.design_notes:
        lines += ["## Visit selection", ""] + [f"- {n}" for n in p.design_notes] + [""]
    if p.open_questions:
        lines += ["## Out of scope / expert decisions required", ""] + [f"- {q}" for q in p.open_questions] + [""]
    lines += ["## Endpoints (data structures)", "",
              "| id | compartment | method | isotype | assay | unit | normalisation | primary |",
              "|---|---|---|---|---|---|---|---|"]
    for e in p.endpoints:
        lines.append(
            f"| {e.endpoint_id} | {e.compartment.value} | {e.method.value} | {e.isotype.value} | "
            f"{e.assay.value} | {e.unit.value} | {e.normalization.value} | {'yes' if e.primary else ''} |"
        )
    return "\n".join(lines) + "\n"
