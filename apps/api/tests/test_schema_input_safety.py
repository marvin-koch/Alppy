"""What a request body is allowed to say, and what it is silently not.

Two findings that look unrelated and are the same shape: both are rules the
schemas already enforce, and neither was written down anywhere a change would
have to pass.

**T15 — mass assignment.** A teacher posts a sheet; the body also carries
``school_id``. Today that field is dropped, because ``ApiModel``'s
``model_config`` does not set ``extra`` and Pydantic's default is ``ignore``.
The product is therefore safe *by a default nobody chose*. One line —
``extra='allow'`` on a base class, or a schema that adds a convenience field
whose name happens to match a column — turns a request body into a way of
writing a tenant id, an approval, or a printed-at timestamp. These tests are
what makes that line fail.

Three families of field are worth naming separately, because they fail
differently:

* ``school_id`` — the tenant. Settable from a body and the whole two-layer
  tenancy story is decoration: the caller picks the school.
* ``approved_at`` — the gate in front of printing AI-generated work
  (DC-content-05). Settable from a body and a model's exercise reaches a
  photocopier without a teacher ever seeing it.
* ``printed_at`` / ``rendered_at`` / ``points_possible`` — facts the product
  derives. Settable from a body and the record stops describing what happened.

**T16 — canton validation.** ``_validate_canton`` is what stands between a
typo and a curriculum mapping: ``School.canton`` is a ``String(2)``, so before
it existed, "XX" was stored happily and the mapping keyed on it. It had no
test, and neither did the deliberate asymmetry in it — case is forgiven, a
non-canton is not.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel, ValidationError

from alppy.schemas import (
    SWISS_CANTONS,
    ChapterCreate,
    ClassCreate,
    ClassUpdate,
    ExerciseCreate,
    ExerciseUpdate,
    SchoolCreate,
    SheetCreate,
    SheetUpdate,
    StudentUpdate,
    SubjectCreate,
)

# --- T15 · mass assignment --------------------------------------------------

#: A minimal valid body per schema, so each test spoils exactly one thing.
_VALID: dict[type[BaseModel], dict[str, object]] = {
    ClassCreate: {"code": "7B", "subject_ids": []},
    ClassUpdate: {"code": "7C"},
    SubjectCreate: {"key": "mathematics", "labels": {"fr": "Maths"}},
    ChapterCreate: {
        "subject_id": str(uuid.uuid4()),
        "key": "fractions",
        "labels": {"fr": "Fractions"},
    },
    StudentUpdate: {"first_name": "Lea", "last_name": "Roth"},
    SheetCreate: {
        "class_id": str(uuid.uuid4()),
        "subject_id": str(uuid.uuid4()),
        "title": "Fractions",
        "language": "fr",
        "items": [{"exercise_id": str(uuid.uuid4()), "position": 0}],
    },
    SheetUpdate: {"title": "Fractions, revised"},
    ExerciseCreate: {
        "subject_id": str(uuid.uuid4()),
        "type": "mcq",
        "language": "fr",
        "statement": "2/3 + 1/3 ?",
        "difficulty": 2,
        "options": ["1", "1/3"],
        "answer_index": 0,
    },
    ExerciseUpdate: {"statement": "5/6 - 1/6 ?"},
}

#: Names a body must never be able to set, and what each one would cost.
_FORBIDDEN: dict[str, str] = {
    "school_id": "the tenant: settable from a body and the caller picks the school",
    "id": "the primary key: settable from a body and a create becomes an overwrite",
    "approved_at": (
        "the gate in front of printing generated work (DC-content-05): settable "
        "from a body and a model's exercise reaches a photocopier unreviewed"
    ),
    "printed_at": "a derived fact about what happened at the photocopier",
    "rendered_at": "a derived fact about what the render job did",
    "points_possible": "derived from the items, not stated by the caller",
    "person_id": "the durable identity a pupil's whole record hangs off (D87)",
    "created_at": "the database's own answer, not the caller's",
    "updated_at": "the database's own answer, not the caller's",
}


@pytest.mark.parametrize("schema", list(_VALID), ids=lambda s: s.__name__)
def test_a_body_cannot_smuggle_a_field_the_server_owns(schema: type[BaseModel]) -> None:
    """Post every forbidden name at once; none may survive onto the model.

    All of them in one body rather than one at a time, because that is the
    request an attacker actually sends, and because a schema that started
    accepting `extra='allow'` would fail this once rather than nine times.
    """
    smuggled = {name: _plausible(name) for name in _FORBIDDEN}
    model = schema(**{**_VALID[schema], **smuggled})  # type: ignore[arg-type]

    for name, why in _FORBIDDEN.items():
        if name in type(model).model_fields:
            continue  # a field the schema declares on purpose — see below
        assert not hasattr(model, name), (
            f"{schema.__name__} accepted {name!r} from the request body. {why}."
        )


@pytest.mark.parametrize("schema", list(_VALID), ids=lambda s: s.__name__)
def test_no_tenant_scoped_schema_declares_a_field_the_server_owns(
    schema: type[BaseModel],
) -> None:
    """The other half, and the one a future change is more likely to trip.

    The test above proves an *undeclared* field is dropped. This proves nobody
    declared one — a schema that adds `school_id` as a convenience is accepting
    it legitimately, and the drop test would go on passing.
    """
    declared = set(type(schema(**_VALID[schema])).model_fields)  # type: ignore[arg-type]
    overlap = declared & set(_FORBIDDEN)
    assert not overlap, (
        f"{schema.__name__} declares {sorted(overlap)}, which the server owns: "
        + "; ".join(_FORBIDDEN[n] for n in sorted(overlap))
    )


def _plausible(name: str) -> object:
    if name.endswith("_id"):
        return str(uuid.uuid4())
    if name.endswith("_at"):
        return "2020-01-01T00:00:00Z"
    return 999


def test_the_guarantee_is_pinned_rather_than_inherited() -> None:
    """`extra` is what all of the above rests on, so say so out loud.

    Pydantic's default is `ignore` and the schemas do not set it. That is the
    correct behaviour and it is currently a default rather than a decision —
    this is the test that notices if someone sets `allow`.
    """
    for schema in _VALID:
        extra = schema.model_config.get("extra", "ignore")
        assert extra in ("ignore", "forbid"), (
            f"{schema.__name__} sets extra={extra!r}: a request body can now "
            f"write any attribute whose name it guesses"
        )


# --- T16 · canton validation ------------------------------------------------


def test_all_twenty_six_cantons_are_accepted() -> None:
    """All 26 rather than the pilot pair: a school in a canton nobody has
    piloted should be refused for being wrong, never for being unexpected."""
    assert len(SWISS_CANTONS) == 26
    for code in sorted(SWISS_CANTONS):
        assert SchoolCreate(name="CO", canton=code).canton == code


@pytest.mark.parametrize("typed", ["vs", "Vs", "zH", "be"])
def test_case_is_forgiven(typed: str) -> None:
    """A teacher typing "vs" means Valais, and telling them so is pedantry."""
    assert SchoolCreate(name="CO", canton=typed).canton == typed.upper()


def test_padding_is_refused_by_length_before_the_validator_sees_it() -> None:
    """A nuance worth pinning rather than discovering later.

    `_validate_canton` opens with `value.strip()`, which reads as "whitespace is
    forgiven". It is not: `canton` is `Annotated[str, Field(max_length=2)]` and a
    plain `field_validator` runs AFTER the field constraints, so " zh " is
    rejected for being four characters and the strip never runs on it. The
    `.strip()` is reachable only for input already short enough — which is why
    an all-whitespace value still normalises to None below.

    Recorded as the current contract, not endorsed: the message a teacher sees
    for " zh " is "String should have at most 2 characters", which describes the
    column rather than the mistake.
    """
    with pytest.raises(ValidationError, match="at most 2 characters"):
        SchoolCreate(name="CO", canton=" zh ")


@pytest.mark.parametrize("bogus", ["XX", "ZZ", "ZU", "CH", "Z", "42"])
def test_a_code_that_is_not_a_canton_is_refused(bogus: str) -> None:
    """The asymmetry is the point: case is a typo, a non-canton is a fact.

    `School.canton` is a `String(2)`, so before this validator existed "ZU" —
    one key away from "ZH" — was stored and the curriculum mapping keyed on it.
    """
    with pytest.raises(ValidationError, match="not a Swiss canton"):
        SchoolCreate(name="CO", canton=bogus)


@pytest.mark.parametrize("blank", [None, "", " ", "  "])
def test_no_canton_is_allowed_and_normalises_to_none(blank: str | None) -> None:
    """The column is nullable: a school that has not said is not a school that
    said something wrong.

    " " and "  " are where the validator's `.strip()` is actually reachable —
    they are short enough to get past `max_length` — and they normalise to None
    rather than to a two-space canton code.
    """
    assert SchoolCreate(name="CO", canton=blank).canton is None


@pytest.mark.parametrize("too_long", ["GVE", "V S", "   ", "ZURICH"])
def test_anything_longer_than_a_code_is_refused_for_its_length(too_long: str) -> None:
    """Same outcome, different reason, and the reason is the point.

    These never reach `_validate_canton` at all, so a test that expected "not a
    Swiss canton" here would be asserting a message the product does not
    produce.
    """
    with pytest.raises(ValidationError, match="at most 2 characters"):
        SchoolCreate(name="CO", canton=too_long)
