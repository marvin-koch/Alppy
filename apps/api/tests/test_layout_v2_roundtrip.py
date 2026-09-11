"""Print a v2 page, photograph it badly, read it back (audit 03, B4).

The codec tests prove the bits survive arithmetic. This proves the *paper*
survives a phone camera and a photocopier — which is the only claim that
matters, and the one the audit said must run against **both** layouts before
`LAYOUT_VERSION` moves.

v1 is exercised alongside v2 throughout, because the risk B4 carries is not that
v2 fails. It is that v2 works and v1 quietly stops.
"""

from __future__ import annotations

import pytest

from alppy.scan.detector import read_uid_grid, register
from alppy.scan.synthetic import copier, phone_photo, render_page
from alppy.sheets import layout as L
from alppy.sheets.uid_code import CANTON_UNSET, PageCode

UID = "7B_15"
COUNTS = [4, 4, 4]
MARKS: list[int | None] = [0, 1, 2]


def _code(**over: object) -> PageCode:
    base: dict[str, object] = {
        "uid": UID,
        "school_year": 5,
        "page_in_copy": 3,
        "canton": 21,
        "nonce": 5_123_456,
    }
    base.update(over)
    return PageCode(**base)  # type: ignore[arg-type]


def _read(image, version: str):
    reg = register(image)
    return read_uid_grid(reg.canonical, layout_version=version)


@pytest.mark.parametrize("degrade", ["none", "phone_photo", "copier"])
def test_a_v2_page_survives_the_degradation_suite(degrade: str) -> None:
    """The whole page code, back intact, off a bad photograph.

    Not just the UID: the page number and the nonce are what B5 and the
    wrong-sheet check will rest on, so a scheme that recovers the pupil and
    garbles the rest would be worse than useless — it would look like it worked.
    """
    code = _code()
    sheet = render_page(
        UID, COUNTS, MARKS, pencil=0.95, layout_version="v2", page_code=code
    )
    image = sheet.image
    if degrade == "phone_photo":
        image = phone_photo(image, seed=3)
    elif degrade == "copier":
        image = copier(image, seed=3)

    uid, confidence, _fills, read_back = _read(image, "v2")
    assert uid == UID, degrade
    assert read_back == code, f"{degrade}: the page code came back changed"
    assert confidence > 0.0


@pytest.mark.parametrize("degrade", ["none", "phone_photo", "copier"])
def test_v1_still_survives_the_same_suite(degrade: str) -> None:
    """The regression that matters. Two live layouts, and v1 is the one with
    paper already in circulation."""
    sheet = render_page(UID, COUNTS, MARKS, pencil=0.95, layout_version="v1")
    image = sheet.image
    if degrade == "phone_photo":
        image = phone_photo(image, seed=3)
    elif degrade == "copier":
        image = copier(image, seed=3)

    uid, _confidence, _fills, page_code = _read(image, "v1")
    assert uid == UID, degrade
    assert page_code is None, "v1 carries no page code and must not invent one"


def test_reading_a_v2_page_as_v1_does_not_name_a_pupil() -> None:
    """The cross-version hazard, from the other side.

    v1 samples the top-left 8x4 of a grid that now starts higher and runs
    wider, so it reads *something*. The CRC is what must turn that into a
    refusal rather than a different, real child.
    """
    sheet = render_page(
        UID, COUNTS, MARKS, pencil=0.95, layout_version="v2", page_code=_code()
    )
    uid, _confidence, _fills, _code_read = _read(sheet.image, "v1")
    assert uid is None


def test_reading_a_v1_page_as_v2_does_not_name_a_pupil() -> None:
    """And the direction the pipeline is most likely to get wrong, since v2
    becomes the default and v1 is what is already in the drawer."""
    sheet = render_page(UID, COUNTS, MARKS, pencil=0.95, layout_version="v1")
    uid, _confidence, _fills, page_code = _read(sheet.image, "v2")
    assert uid is None
    assert page_code is None


def test_the_v2_grid_clears_the_items_region_and_the_fiducials() -> None:
    """Geometry, asserted rather than eyeballed.

    Six rows at v1's origin would have printed over the first exercise. The
    grid moved up instead of the items moving down, because
    `ANSWER_BOX_MAX_LINES` is calibrated to the millimetre against that region.
    """
    grid = L.uid_grid("v2")
    x0, y0 = grid.origin_mm
    right_fiducial_left = L.FIDUCIAL_CENTRES_MM["tr"][0] - L.FIDUCIAL_MM / 2.0

    assert y0 + grid.height_mm <= L.ITEMS_TOP_MM, "the grid would print over item 1"
    assert x0 + grid.width_mm < right_fiducial_left, "the grid touches the fiducial"
    assert y0 >= L.MARGIN_MM, "the grid runs off the top of the page"


def test_every_page_of_a_multi_page_copy_is_distinguishable() -> None:
    """B5's real fix: the paper says which page it is.

    Under v1 every page of one pupil's copy carries an identical grid, which is
    why the pipeline had to count uploads to tell them apart — and why a
    re-shot page silently became page 1.
    """
    seen = set()
    for page in range(1, 5):
        sheet = render_page(
            UID, COUNTS, MARKS, pencil=0.95,
            layout_version="v2", page_code=_code(page_in_copy=page),
        )
        _uid, _confidence, _fills, code = _read(sheet.image, "v2")
        assert code is not None and code.page_in_copy == page
        seen.add(tuple(sheet.image.flatten()[::997].tolist()))
    assert len(seen) == 4, "four pages of one copy printed identical grids"


def test_a_copy_with_no_declared_canton_round_trips() -> None:
    """`School.canton` is nullable, so `CANTON_UNSET` has to survive paper."""
    code = _code(canton=CANTON_UNSET)
    sheet = render_page(
        UID, COUNTS, MARKS, pencil=0.95, layout_version="v2", page_code=code
    )
    _uid, _confidence, _fills, read_back = _read(sheet.image, "v2")
    assert read_back == code
