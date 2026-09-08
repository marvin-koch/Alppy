"""Cutting a box out of a page: Alppy's ink goes, the student's stays."""

from __future__ import annotations

import numpy as np
import pytest

from alppy.models.enums import AnswerBoxFill
from alppy.scan.answer_box import (
    BLANK_INK_RATIO,
    BoxRect,
    crop_answer_box,
    encode_png,
)
from alppy.scan.detector import PX_PER_MM, register
from alppy.scan.synthetic import draw_answer_box, phone_photo, render_page, scribble
from alppy.sheets import layout as L

RECT = BoxRect(x_mm=17.0, y_mm=90.0, w_mm=176.0, h_mm=40.0)


def _page(*, fill: str, ink: bool, shade: int = 0) -> np.ndarray:
    sheet = render_page("7B_01", [4, 0], [1, None])
    draw_answer_box(sheet.image, RECT.x_mm, RECT.y_mm, RECT.w_mm, RECT.h_mm, fill=fill)
    if ink:
        scribble(sheet.image, RECT.x_mm, RECT.y_mm, RECT.w_mm, RECT.h_mm, shade=shade)
    return sheet.image


@pytest.mark.parametrize("fill", ["lined", "grid", "blank"])
def test_an_empty_box_comes_back_blank_whatever_it_was_printed_with(fill: str) -> None:
    """The border, the ticks and the guides are Alppy's; once they are gone an
    unanswered box holds no ink at all."""
    crop = crop_answer_box(_page(fill=fill, ink=False), RECT, fill=AnswerBoxFill(fill))
    assert crop.blank, f"{fill}: ink ratio {crop.ink_ratio:.4f}"
    assert crop.ink_ratio < BLANK_INK_RATIO / 3
    assert crop.blank_confidence > 0.6
    h, w = crop.image.shape
    assert (h, w) == (round(RECT.h_mm * PX_PER_MM), round(RECT.w_mm * PX_PER_MM))


@pytest.mark.parametrize("fill", ["lined", "grid", "blank"])
def test_pen_survives_the_guides(fill: str) -> None:
    crop = crop_answer_box(_page(fill=fill, ink=True), RECT, fill=AnswerBoxFill(fill))
    assert not crop.blank
    assert crop.ink_ratio > BLANK_INK_RATIO * 10
    # Most of the stroke is kept: only a hair on each guide is painted out.
    reference = crop_answer_box(_page(fill="blank", ink=True), RECT, fill=AnswerBoxFill.BLANK)
    assert crop.ink_ratio > reference.ink_ratio * 0.8


def test_pencil_survives_too() -> None:
    crop = crop_answer_box(_page(fill="lined", ink=True, shade=95), RECT, fill=AnswerBoxFill.LINED)
    assert not crop.blank


def test_the_crop_is_cut_from_the_registered_page_even_off_a_phone_photo() -> None:
    """Registration puts the box back where it was measured, so the same
    rectangle works on a photo taken at an angle."""
    photo = phone_photo(_page(fill="lined", ink=True), seed=3)
    canonical = register(photo).canonical
    crop = crop_answer_box(canonical, RECT, fill=AnswerBoxFill.LINED)
    assert not crop.blank
    empty = register(phone_photo(_page(fill="lined", ink=False), seed=3)).canonical
    assert crop_answer_box(empty, RECT, fill=AnswerBoxFill.LINED).blank


def test_a_box_off_the_page_is_refused() -> None:
    with pytest.raises(ValueError):
        crop_answer_box(_page(fill="blank", ink=False), BoxRect(300.0, 10.0, 20.0, 20.0), fill=AnswerBoxFill.BLANK)


def test_the_crop_encodes_as_a_png() -> None:
    crop = crop_answer_box(_page(fill="lined", ink=True), RECT, fill=AnswerBoxFill.LINED)
    assert encode_png(crop.image)[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_rectangle_sits_inside_the_statement_region() -> None:
    assert RECT.y_mm > L.ITEMS_TOP_MM and RECT.y_mm + RECT.h_mm < L.ITEMS_BOTTOM_MM
