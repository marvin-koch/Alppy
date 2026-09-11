// AUTO-GENERATED — DO NOT EDIT.
// Source of truth: apps/api/alppy/api/errors.py, plus every
// `code="..."` raised under apps/api/alppy/.
// Regenerate with: PYTHONPATH=apps/api python scripts/generate-api-types.py

/**
 * Every `code` the error envelope can carry.
 *
 * `scripts/check-i18n.mjs` asserts that each one has a sentence in all
 * three catalogues. The catalogue used to cover thirteen of them, so a
 * teacher meeting any of the rest read the generic fallback — which is
 * how a rate limit, a permission refusal and a dead API all came to say
 * the same thing (F14).
 */
export const API_ERROR_CODES = [
  'bad_request',
  'branch_holds_sheets',
  'conflict',
  'detection_not_corrected',
  'fallback',
  'forbidden',
  'http_error',
  'idempotency_in_flight',
  'idempotency_key_too_long',
  'internal_error',
  'method_not_allowed',
  'network_error',
  'not_found',
  'payload_too_large',
  'rate_limited',
  'scan_already_confirmed',
  'scan_confirmed',
  'scan_low_confidence_unreviewed',
  'scan_matches_no_sheet',
  'scan_no_sheet',
  'scan_not_confirmed',
  'scan_open_grading_pending',
  'scan_pages_unassigned',
  'scan_processing',
  'school_last_teacher',
  'service_unavailable',
  'sheet_not_renderable',
  'teacher_still_head',
  'unauthorized',
  'unprocessable',
  'unsupported_media_type',
  'validation_error',
] as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

/** The 26 Swiss cantons, as `schemas.SWISS_CANTONS` validates them. */
export const SWISS_CANTONS = [
  'AG',
  'AI',
  'AR',
  'BE',
  'BL',
  'BS',
  'FR',
  'GE',
  'GL',
  'GR',
  'JU',
  'LU',
  'NE',
  'NW',
  'OW',
  'SG',
  'SH',
  'SO',
  'SZ',
  'TG',
  'TI',
  'UR',
  'VD',
  'VS',
  'ZG',
  'ZH',
] as const;

export type SwissCanton = (typeof SWISS_CANTONS)[number];
