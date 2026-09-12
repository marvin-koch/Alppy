import { beforeEach, describe, expect, it } from 'vitest';

import type { DetectionOut } from '@/lib/api/types';

import { alreadyApplied, loadUnsaved, saveUnsaved } from './unsavedCorrections';

const detection = (over: Partial<DetectionOut>): DetectionOut =>
  ({ id: 'd1', outcome: 'detected', detected_index: 0, verdict_correct: null, transcription: null, ...over }) as DetectionOut;

describe('unsaved corrections', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('survives a reload of the screen, per pile', () => {
    saveUnsaved('scan-a', new Map([['d1', { verdict_correct: false }]]));
    expect(loadUnsaved('scan-a').get('d1')).toEqual({ verdict_correct: false });
    expect(loadUnsaved('scan-b').size).toBe(0);
  });

  it('clears the key when nothing is left', () => {
    saveUnsaved('scan-a', new Map([['d1', { detected_index: 2 }]]));
    saveUnsaved('scan-a', new Map());
    expect(window.sessionStorage.length).toBe(0);
  });

  it('ignores a corrupt record rather than breaking the screen', () => {
    window.sessionStorage.setItem('alppy.unsaved-corrections.scan-a', '{not json');
    expect(loadUnsaved('scan-a').size).toBe(0);
  });

  it('knows when the server already holds the correction', () => {
    expect(alreadyApplied(detection({ outcome: 'corrected', detected_index: 2 }), { detected_index: 2 })).toBe(true);
    expect(alreadyApplied(detection({ outcome: 'corrected', detected_index: 1 }), { detected_index: 2 })).toBe(false);
    // The machine's reading matching by coincidence is not a saved correction.
    expect(alreadyApplied(detection({ outcome: 'detected', detected_index: 2 }), { detected_index: 2 })).toBe(false);
    expect(
      alreadyApplied(detection({ outcome: 'corrected', verdict_correct: false }), { verdict_correct: false }),
    ).toBe(true);
  });
});
