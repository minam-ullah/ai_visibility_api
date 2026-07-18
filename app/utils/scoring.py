"""Opportunity score formula.

opportunity_score (0.0-1.0) estimates how valuable it would be for the target
domain to appear in the AI-generated answer for a given query. It is a
weighted blend of four normalised factors:

    score = 0.35 * volume_norm
          + 0.25 * (1 - difficulty_norm)
          + 0.25 * visibility_gap
          + 0.15 * intent_weight

- volume_norm (0-1): log-scaled search volume, so a jump from 100->1000
  matters as much as 1000->10000 rather than raw volume swamping everything
  else. log10(volume+1) / log10(20000) is clamped to [0, 1] -- 20k/mo is
  treated as "effectively saturated" for this long-tail, commercial-intent
  query set.
- (1 - difficulty_norm): easier queries (low competitive_difficulty 0-100)
  are more capturable, so this term is inverted -- low difficulty raises the
  score.
- visibility_gap: 1.0 if the domain does NOT currently appear in the AI
  answer (the whole gap is open), 0.0 if it already appears. This is
  deliberately the single biggest lever after volume, since "not showing up
  at all" is the core problem this product solves.
- intent_weight: comparison and best-of queries convert better than pure
  informational queries, since the reader is already evaluating vendors.
  comparison/best_of = 1.0, transactional = 0.8, informational = 0.5.

Weights were chosen so that a high-volume, low-difficulty, invisible,
comparison query lands near 1.0, and a low-volume, high-difficulty,
already-visible, informational query lands near 0.0. There's no single
"correct" formula here -- volume and the visibility gap are given the most
weight because they most directly map to business impact (traffic potential
x whether there's a gap to close at all).
"""
import math

_INTENT_WEIGHTS = {
    "comparison": 1.0,
    "best_of": 1.0,
    "transactional": 0.8,
    "informational": 0.5,
}

_VOLUME_CEILING = 20_000  # volumes above this are treated as saturated (norm -> 1.0)


def compute_opportunity_score(
    *,
    search_volume: int,
    competitive_difficulty: int,
    domain_visible: bool,
    intent: str = "informational",
) -> float:
    volume = max(0, search_volume or 0)
    volume_norm = min(1.0, math.log10(volume + 1) / math.log10(_VOLUME_CEILING + 1))

    difficulty = max(0, min(100, competitive_difficulty or 0))
    difficulty_norm = difficulty / 100.0

    visibility_gap = 0.0 if domain_visible else 1.0
    intent_weight = _INTENT_WEIGHTS.get(intent, 0.5)

    score = (
        0.35 * volume_norm
        + 0.25 * (1 - difficulty_norm)
        + 0.25 * visibility_gap
        + 0.15 * intent_weight
    )
    return round(max(0.0, min(1.0, score)), 4)
