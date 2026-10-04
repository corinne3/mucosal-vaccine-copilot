"""Objective 1 — the domain model must refuse incoherent designs."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mvc.schema import (
    ALL_MODELS,
    Arm,
    AssayType,
    Compartment,
    ImmuneEndpoint,
    Isotype,
    Platform,
    Population,
    Route,
    SamplingEvent,
    SamplingMethod,
    TrialDesign,
    Unit,
    Vaccine,
)


@pytest.fixture
def laiv() -> Vaccine:
    return Vaccine(name="LAIV", pathogen="influenza",
                   platform=Platform.live_attenuated, route=Route.intranasal)


def test_mucosal_route_flag(laiv):
    assert laiv.is_mucosal_route
    im = laiv.model_copy(update={"route": Route.intramuscular})
    assert not im.is_mucosal_route


def test_compartment_is_mucosal():
    assert Compartment.nasal.is_mucosal and Compartment.oral.is_mucosal
    assert not Compartment.serum.is_mucosal and not Compartment.blood_cells.is_mucosal


def test_endpoint_rejects_method_compartment_mismatch():
    """A serum tube cannot measure the nasal compartment."""
    with pytest.raises(ValidationError, match="does not sample compartment"):
        ImmuneEndpoint(endpoint_id="bad", label="bad", compartment=Compartment.nasal,
                       method=SamplingMethod.serum, isotype=Isotype.IgA,
                       assay=AssayType.elisa_binding, unit=Unit.au_ml)


def test_sampling_event_derives_compartment():
    assert SamplingEvent(day=7, method=SamplingMethod.nasosorption).compartment == Compartment.nasal
    assert SamplingEvent(day=7, method=SamplingMethod.saliva).compartment == Compartment.oral


def test_arm_requires_sorted_doses(laiv):
    with pytest.raises(ValidationError, match="sorted"):
        Arm(arm_id="A", vaccine=laiv, dose_days=[28, 0], n_participants=10)


def test_population_age_order():
    with pytest.raises(ValidationError, match="age_min"):
        Population(age_min=50, age_max=18)


def _design(**kw) -> TrialDesign:
    v = Vaccine(name="LAIV", pathogen="influenza", platform=Platform.live_attenuated,
                route=Route.intranasal)
    base = dict(
        trial_id="t1", title="t", arms=[Arm(arm_id="A", vaccine=v, n_participants=10)],
        sampling=[SamplingEvent(day=0, method=SamplingMethod.nasosorption),
                  SamplingEvent(day=28, method=SamplingMethod.nasosorption)],
        endpoints=[ImmuneEndpoint(endpoint_id="e", label="e", compartment=Compartment.nasal,
                                  method=SamplingMethod.nasosorption, isotype=Isotype.sIgA,
                                  assay=AssayType.elisa_binding, unit=Unit.ratio)],
        follow_up_days=180,
    )
    base.update(kw)
    return TrialDesign(**base)


def test_design_valid():
    d = _design()
    assert d.sampling_days(SamplingMethod.nasosorption) == [0, 28]


def test_design_rejects_endpoint_without_sampling():
    """An endpoint you never collect a sample for is a silent protocol bug."""
    with pytest.raises(ValidationError, match="without matching sampling"):
        _design(endpoints=[ImmuneEndpoint(
            endpoint_id="serum", label="serum", compartment=Compartment.serum,
            method=SamplingMethod.serum, isotype=Isotype.IgG,
            assay=AssayType.elisa_binding, unit=Unit.bau_ml)])


def test_design_rejects_sampling_after_followup():
    with pytest.raises(ValidationError, match="after end of follow-up"):
        _design(sampling=[SamplingEvent(day=0, method=SamplingMethod.nasosorption),
                          SamplingEvent(day=400, method=SamplingMethod.nasosorption)],
                follow_up_days=180)


def test_extra_fields_forbidden(laiv):
    with pytest.raises(ValidationError):
        Vaccine(name="x", pathogen="influenza", platform=Platform.mrna,
                route=Route.intranasal, unexpected_field=1)


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__name__)
def test_json_schema_exports(model):
    schema = model.model_json_schema()
    assert json.dumps(schema)
    assert schema.get("title") == model.__name__
