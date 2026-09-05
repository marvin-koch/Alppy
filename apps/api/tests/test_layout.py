"""Sheet layout geometry — the contract between print, PDF and the detector."""

from __future__ import annotations

import pytest

from alppy.sheets import layout as L


def test_frame_derives_from_fiducial_centres() -> None:
    assert L.FRAME_X0_MM == L.MARGIN_MM + L.FIDUCIAL_MM / 2
    assert pytest.approx(L.PAGE_W_MM - 2 * L.FRAME_X0_MM) == L.FRAME_W_MM
    assert pytest.approx(L.PAGE_H_MM - 2 * L.FRAME_Y0_MM) == L.FRAME_H_MM


def test_all_four_fiducials_are_inside_the_page() -> None:
    half = L.FIDUCIAL_MM / 2
    for cx, cy in L.FIDUCIAL_CENTRES_MM.values():
        assert half <= cx <= L.PAGE_W_MM - half
        assert half <= cy <= L.PAGE_H_MM - half


def test_every_bubble_lies_inside_the_registration_frame() -> None:
    """If a bubble fell outside the frame the detector could not address it."""
    for slot in L.page_slots(0, [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE):
        assert 0.0 < slot.u < 1.0, f"item {slot.item_index} option {slot.option_index}"
        assert 0.0 < slot.v < 1.0, f"item {slot.item_index} option {slot.option_index}"


def test_bubbles_never_overlap_the_fiducials() -> None:
    """A bubble under a corner mark would be unreadable and would also break
    registration. This is the check that caught a 2 mm clash during design."""
    half_f = L.FIDUCIAL_MM / 2
    half_b = L.BUBBLE_D_MM / 2
    for slot in L.page_slots(0, [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE):
        for fx, fy in L.FIDUCIAL_CENTRES_MM.values():
            overlap_x = abs(slot.cx_mm - fx) < (half_f + half_b)
            overlap_y = abs(slot.cy_mm - fy) < (half_f + half_b)
            assert not (overlap_x and overlap_y)


def test_bubbles_do_not_overlap_each_other() -> None:
    slots = L.page_slots(0, [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE)
    centres = [(s.cx_mm, s.cy_mm) for s in slots]
    assert len(set(centres)) == len(centres)
    for i, (x1, y1) in enumerate(centres):
        for x2, y2 in centres[i + 1 :]:
            distance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            assert distance >= L.BUBBLE_D_MM, f"bubbles {distance:.1f}mm apart"


def test_answer_grid_sits_below_the_statement_region() -> None:
    assert L.ITEMS_BOTTOM_MM <= L.GRID_TOP_MM
    assert L.ITEMS_TOP_MM < L.ITEMS_BOTTOM_MM


def test_uid_grid_cells_do_not_overlap() -> None:
    centres = [
        L.uid_cell_centre_mm(s, r)
        for s in range(L.UID_GRID_CELLS)
        for r in range(L.UID_GRID_ROWS)
    ]
    assert len(set(centres)) == len(centres)


def test_item_index_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        L.bubble_centre_mm(L.ITEMS_PER_PAGE, 0)
    with pytest.raises(ValueError):
        L.bubble_centre_mm(0, L.MAX_OPTIONS)
    with pytest.raises(ValueError):
        L.bubble_centre_mm(-1, 0)


def test_free_text_items_get_no_bubbles() -> None:
    """`open` exercises are printed but never auto-graded, so they claim no
    slot on the answer grid."""
    assert L.page_slots(0, [0, 4, 2]) == [
        s for s in L.page_slots(0, [0, 4, 2]) if s.item_index in (1, 2)
    ]
    assert all(s.item_index != 0 for s in L.page_slots(0, [0, 4, 2]))


def test_true_false_letters_follow_the_sheet_language() -> None:
    assert L.tf_letters("fr") == "VF"
    assert L.tf_letters("de") == "RF"
    assert L.tf_letters("en") == "TF"
    assert L.tf_letters("it") == "TF"


def test_serialisable_form_is_complete() -> None:
    d = L.as_dict()
    assert d["layoutVersion"] == L.LAYOUT_VERSION
    assert d["itemsPerPage"] == L.ITEMS_PER_PAGE
    assert set(d["fiducialCentresMm"]) == {"tl", "tr", "bl", "br"}
