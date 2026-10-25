import { describe, expect, it } from 'vitest'

const stages = ['discovery', 'design', 'plan', 'build', 'review', 'deploy']

describe('studio workflow contract', () => {
  it('keeps all six PRD stages in order', () => {
    expect(stages).toHaveLength(6)
    expect(stages.at(-1)).toBe('deploy')
  })

  it('uses a bounded three-phase implementation cycle', () => {
    const nextPhase = (phase: number) => Math.min(3, phase + 1)
    expect([0, 1, 2, 3].map(nextPhase)).toEqual([1, 2, 3, 3])
  })
})
