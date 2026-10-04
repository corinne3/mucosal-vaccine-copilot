"""Table 1 of the workshop report, and what the engine makes of it.

These tests guard a transcription as much as a computation. Encoded data drifts
silently: a cell gets "tidied", a mapping gets widened to make a warning go
away, and six months later the dashboard is making a claim about a published
table that the table does not support. So the assertions below are deliberately
specific about the *source*, not only about the code.
"""

from __future__ import annotations

import json

from mvc.consortia import (
    TABLE1_PATH,
    cross_consortium_matrix,
    cross_consortium_summary,
    load_table1,
    metadata_gap_report,
    shared_methods,
)
from mvc.schema import METHOD_COMPARTMENT, Compartment, MeasurementContext

# --- the transcription ------------------------------------------------------

def test_the_six_consortia_of_table_1_are_all_present():
    t1 = load_table1()
    assert t1.consortia == [
        "COMMUNITY", "GERMINATE", "MOVE", "MUSICC", "Project NextGen", "VAXXAIR"]


def test_registered_trials_keep_their_registration_number():
    """The NCT number is how a reader checks the claim. Losing it loses the audit trail."""
    t1 = load_table1()
    by_name = {s.consortium: s.registration for s in t1.series}
    assert by_name["COMMUNITY"] == "NCT06784739"
    assert by_name["GERMINATE"] == "NCT06620185"
    assert by_name["VAXXAIR"] == "NCT05921448"


def test_every_table_1_cell_is_either_mapped_or_recorded_as_unmodelled():
    """No cell may be silently dropped.

    `load_table1` raises on an unknown cell, so this test mainly pins the
    second half of the contract: cells that map to null must come back in
    `unmodelled` with a reason, not vanish.
    """
    raw = json.loads(TABLE1_PATH.read_text())
    t1 = load_table1()
    unmodelled = {(u.consortium, u.verbatim) for u in t1.unmodelled}
    for c in raw["consortia"]:
        for cell in c["upper_airway_verbatim"] + c["lower_airway_verbatim"]:
            if raw["method_mapping"][cell] is None:
                assert (c["name"], cell) in unmodelled
        for cell in c["assays_verbatim"]:
            if raw["assay_mapping"][cell] is None:
                assert (c["name"], cell) in unmodelled
    assert all(u.reason for u in t1.unmodelled), "an unmodelled cell without a reason"


def test_environmental_sampling_is_not_an_immune_measurement():
    """It samples the room, not the participant. Giving it a measurement context
    would put air on the same axis as a nasal antibody."""
    t1 = load_table1()
    env = [u for u in t1.unmodelled if "Environmental" in u.verbatim]
    assert len(env) == 2, "GERMINATE and MUSICC both do environmental sampling"
    assert all(u.kind == "sampling" for u in env)
    assert not any("Environmental" in s.method_verbatim for s in t1.series)


def test_igg_slash_iga_cells_expand_into_two_series():
    """"Humoral response (IgG/IgA titres)" is two measurements in one cell.

    IgG and IgA in the airway are not interchangeable — that is the project's
    founding claim — so the cell must not collapse to a single series.
    """
    t1 = load_table1()
    germ = [s for s in t1.series
            if s.consortium == "GERMINATE" and s.context.method.value == "nasosorption"]
    isotypes = {s.context.isotype.value for s in germ}
    assert {"IgG", "IgA"} <= isotypes


def test_series_labels_are_unique():
    """Two series that differ only by isotype must not print identically."""
    t1 = load_table1()
    labels = [s.label for s in t1.series]
    assert len(labels) == len(set(labels)), "duplicate labels hide a real distinction"


# --- the model had to grow to hold real data --------------------------------

def test_lower_airway_sampling_is_representable():
    """Table 1 required a compartment and three methods the model did not have.

    BAL dilutes like a nasal lavage; bronchosorption absorbs like nasosorption;
    PExA collects exhaled particles. All three are lower airway, which is a
    different compartment from the nose — comparing across them is precisely
    what COMMUNITY lists as an objective.
    """
    for m in ("bal", "bronchosorption", "pexa"):
        from mvc.schema import SamplingMethod
        assert METHOD_COMPARTMENT[SamplingMethod(m)] is Compartment.lower_airway
    assert Compartment.lower_airway.is_mucosal


def test_upper_and_lower_airway_are_never_comparable():
    from mvc.schema import AssayType, Isotype, Normalization, SamplingMethod, Unit

    def ctx(method):
        return MeasurementContext(
            compartment=METHOD_COMPARTMENT[SamplingMethod(method)],
            method=SamplingMethod(method), isotype=Isotype.IgA,
            assay=AssayType.multiplex_binding, unit=Unit.au_ml,
            normalization=Normalization.none, antigen="HA", lab="x", source="test")

    from mvc.comparability import compare
    assert compare(ctx("nasosorption"), ctx("bal")).label == "not_comparable"


# --- the finding ------------------------------------------------------------

def test_every_consortium_uses_nasosorption():
    """The convergence that is already real, and the reason the gap is worth closing."""
    sm = shared_methods(load_table1())
    row = sm[sm["method"] == "nasosorption"].iloc[0]
    assert row["n_consortia"] == 6


def test_no_cross_consortium_pair_is_ever_fully_comparable():
    """The headline claim of the tab. If this ever passes a 'comparable', the
    claim on screen is false and must be rewritten."""
    s = cross_consortium_summary(load_table1())
    assert len(s) > 100
    assert "comparable" not in set(s["verdict"]), s[s["verdict"] == "comparable"]


def test_the_undecided_pairs_are_exactly_the_conditional_ones():
    """`decided_by_unrecorded_metadata` must mean what the caption says it means:
    nothing *recorded* rules the pair out, so the missing fields decide it."""
    s = cross_consortium_summary(load_table1())
    flagged = set(s.index[s["decided_by_unrecorded_metadata"]])
    conditional = set(s.index[s["verdict"] == "conditional"])
    assert flagged == conditional
    assert flagged, "if nothing is left undecided, the tab has no finding to show"


def test_gap_report_explains_every_field_it_names():
    g = metadata_gap_report(load_table1())
    assert len(g) == 5
    assert set(g["field"]) == {"unit", "normalization", "lloq", "antigen", "lab"}
    assert g["what_it_decides"].str.len().min() > 40
    assert not g["recorded_in_table_1"].any()


def test_matrix_is_square_and_self_consistent():
    t1 = load_table1()
    mat, details = cross_consortium_matrix(t1)
    assert mat.shape[0] == mat.shape[1] == len(t1.series)
    assert all(mat.iloc[i, i] == "self" for i in range(len(t1.series)))
    # the verdict is symmetric: A against B says the same as B against A
    labels = list(mat.index)
    for (a, b), r in list(details.items())[:200]:
        assert details[(b, a)].label == r.label
    assert len(labels) == len(set(labels))
