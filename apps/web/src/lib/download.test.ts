import { describe, expect, it } from 'vitest';

import { exportFilename } from './download';

describe('exportFilename', () => {
  it('is sortable and says what it is', () => {
    expect(exportFilename('7B')).toMatch(/^alppy-7b-\d{4}-\d{2}-\d{2}\.json$/);
  });

  /** `Collège` becomes `college`, not `coll-ge`: a filename a teacher cannot
   *  recognise is one they will not find again. */
  it('strips accents rather than dropping the letters', () => {
    expect(exportFilename('Collège de démonstration')).toContain('college-de-demonstration');
  });

  it('collapses anything a filesystem would argue about', () => {
    expect(exportFilename('7B / groupe "A"')).toMatch(/^alppy-7b-groupe-a-\d{4}-\d{2}-\d{2}\.json$/);
  });

  it('never produces a nameless file', () => {
    expect(exportFilename('///')).toMatch(/^alppy-export-\d{4}-\d{2}-\d{2}\.json$/);
  });
});
