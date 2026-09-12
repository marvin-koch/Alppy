import type { TreeCompetenceOut } from '@/lib/api/types';

/**
 * The code to print for a Competence, disambiguated only when it has to be.
 *
 * A curriculum gets revised, and `uq_competency_code` carries the edition
 * precisely so both wordings can coexist: "the same code means different
 * things in two editions". A school part-way through a migration has Themes
 * hanging off both revisions, so the tree legitimately holds two Competences
 * with an identical code AND an identical label — the demo data has exactly
 * that, two "MSN 34 · Mobiliser la mesure pour comparer des grandeurs" rows
 * with different Themes under each. On screen they were indistinguishable.
 *
 * They are deliberately NOT merged: the model says they may not mean the same
 * thing, so rolling them into one node would invent an equivalence nobody
 * stated. The edition is shown instead, and only on the rows that need it —
 * appending "(2023)" to every code in a school that uses one edition would be
 * noise on every screen to solve a problem almost nobody has.
 */
export function competenceCodes(
  competences: readonly Pick<TreeCompetenceOut, 'competency_id' | 'code' | 'edition'>[],
): Map<string, string> {
  const seen = new Map<string, number>();
  for (const competence of competences) {
    seen.set(competence.code, (seen.get(competence.code) ?? 0) + 1);
  }
  return new Map(
    competences.map((competence) => [
      competence.competency_id,
      seen.get(competence.code)! > 1 && competence.edition
        ? `${competence.code} (${competence.edition})`
        : competence.code,
    ]),
  );
}
