# AI Visibility Intelligence API

A Flask API that registers a business profile, runs a 3-agent AI pipeline to discover
and score high-value AI-search queries in that business's competitive space, and
serves up prioritised content recommendations to close visibility gaps.

## Setup (local, <5 min)

```bash
git clone <this-repo>
cd ai_visibility_api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (or OPENAI_API_KEY + LLM_PROVIDER=openai)

python run.py
# API is now on http://localhost:5000, tables are auto-created on first run
```

Run the tests: `pytest tests/ -v`

### Setup via Docker Compose (bonus)

```bash
cp .env.example .env   # set your LLM API key
docker-compose up --build
```

This starts the API on `:5000` backed by a Postgres container. Comment out the `db`
service and the `DATABASE_URL` override in `docker-compose.yml` if you'd rather keep
SQLite.

### Migrations

The app calls `db.create_all()` on boot for fast local iteration. For a real
migration history:

```bash
flask db init
flask db migrate -m "initial schema"
flask db upgrade
```

## Architecture

```
app/
├── __init__.py          # create_app() factory, blueprint + error handler registration
├── config.py             # env-var driven config (dev / test)
├── extensions.py         # SQLAlchemy + Flask-Migrate singletons
├── models/                # BusinessProfile, PipelineRun, DiscoveredQuery, ContentRecommendation
├── agents/
│   ├── base.py            # shared LLM-call plumbing (BaseAgent.ask)
│   ├── discovery.py        # Agent 1 - Query Discovery
│   ├── scoring.py           # Agent 2 - Visibility Scoring
│   └── recommendation.py    # Agent 3 - Content Recommendation
├── services/
│   ├── llm_client.py        # Anthropic/OpenAI wrapper: JSON extraction + one repair retry
│   ├── search_data.py        # real keyword data (DataForSEO) with a documented mock fallback
│   └── pipeline.py            # orchestrator: Agent1 -> Agent2 (per-query, failure-isolated) -> Agent3
├── api/
│   ├── profiles.py            # /profiles, /profiles/<id>/run, /queries, /recommendations
│   └── queries.py              # /queries/<id>/recheck
└── utils/
    ├── errors.py                # APIError + consistent JSON error responses
    └── scoring.py                 # opportunity score formula
```

Each agent is a plain class with one public method, `run(...)`, and takes an optional
`llm_client` in its constructor — that's what lets `tests/test_agents.py` swap in a
`FakeLLMClient` and unit-test agent logic (prompt construction, response validation,
malformed-JSON handling) with zero network calls.

### Why this agent split

- **Discovery** only knows about the business profile and returns raw candidate
  queries. It never touches the database or scoring logic, so its prompt can be
  iterated on independently of everything downstream.
- **Scoring** is the one agent that mixes a real external data source (keyword
  volume/difficulty from DataForSEO) with an LLM call (simulating whether the
  domain would appear in an AI answer). It's also the only agent invoked outside
  the main pipeline, via `POST /queries/<uuid>/recheck` — keeping it self-contained
  made that reuse trivial.
- **Recommendation** only ever sees already-persisted, already-scored queries
  (specifically the top not-visible ones), so it can't accidentally recommend
  content for a query it hallucinated.

The orchestrator (`services/pipeline.py`) is the only place that knows the three
agents run in sequence — none of the agents know about each other.

### Partial-failure handling

`run_pipeline`:
- Fails the whole run if Agent 1 returns zero usable queries, or if Agent 2 fails
  for *every* query (nothing to build recommendations from).
- If Agent 2 fails for a *single* query, that failure is logged and the query is
  left in the DB with `visibility_status="unknown"` — the loop continues to the
  next query rather than aborting.
- If Agent 3 fails entirely, the run still completes — recommendations are useful
  but not load-bearing for the discovery+scoring result.

## Prompt engineering

All three system prompts (see `app/agents/*.py`) follow the same shape: an explicit
persona and constraints, a numbered rule list (output count, allowed enum values,
tone/style constraints), and a JSON schema block that the prompt says to return
*exactly*, with "no prose before or after". User prompts are plain `.format()`
templates with the profile/query data interpolated in.

`LLMClient.complete_json` (in `services/llm_client.py`) is the single chokepoint all
three agents call through. It:
1. Strips markdown code fences if the model wrapped its JSON in one.
2. Falls back to locating the first balanced `{...}`/`[...]` block if the whole
   response isn't valid JSON on its own.
3. If parsing still fails, sends **one** repair request back to the model with the
   broken output attached and an explicit "return only valid JSON" instruction.
4. Raises `LLMError` only if that also fails — at which point the caller (the
   pipeline's per-query loop, or the route handler for `/recheck`) decides whether
   that's a fatal error or an isolated, skippable one.

Each agent's `_validate()` static method is a second, independent layer of defense
on top of that: even syntactically valid JSON gets checked for required keys,
allowed enum values, and referential integrity (e.g. `ContentRecommendationAgent`
drops any recommendation whose `query_id` doesn't match a query it was actually
given — never trusting the model to only reference IDs it was shown).

## Opportunity score formula

```
score = 0.35 * volume_norm
      + 0.25 * (1 - difficulty_norm)
      + 0.25 * visibility_gap
      + 0.15 * intent_weight
```

- **volume_norm** — `log10(volume + 1) / log10(20001)`, clamped to `[0, 1]`. Log-scaled
  so that 100→1,000 moves the score about as much as 1,000→10,000; raw volume would
  let a single viral head-term swamp everything else in this long-tail query set.
- **difficulty_norm** — `competitive_difficulty / 100`, inverted in the formula
  (`1 - difficulty_norm`) since *low* difficulty is what makes a query capturable.
- **visibility_gap** — `1.0` if the domain does **not** currently appear in the AI
  answer, else `0.0`. Given the second-highest weight deliberately: "not showing
  up at all" is the specific problem this product exists to find and fix.
- **intent_weight** — `comparison`/`best_of` = 1.0, `transactional` = 0.8,
  `informational` = 0.5. A reader asking "X vs Y" or "best tool for X" is already
  evaluating vendors and converts at a different rate than someone asking "how does
  X work".

There's no ground-truth answer here; the weighting reflects a judgment call that
**volume and the visibility gap** are the two levers with the most direct line to
business impact (how many people could see the content, and whether there's
actually a gap to close), so together they're worth 60% of the score. See
`app/utils/scoring.py` for the full implementation and inline reasoning; it's
covered directly by `tests/test_agents.py`.

## External data tradeoffs

The assessment calls for **real** search volume / competition data (e.g.
DataForSEO) rather than fabricated numbers. `app/services/search_data.py`
implements the real DataForSEO `keywords_data/google_ads/search_volume/live`
call, gated on `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` being set in `.env`.

Since a fresh clone won't have paid DataForSEO credentials, and the assessment
also needs to be runnable and reviewable cold, the same function falls back to a
**deterministic, seeded mock generator** (seeded from a hash of the query text, so
results are stable across repeated calls and tests) when those credentials are
absent — and logs a visible warning every time it does so, so nobody mistakes mock
numbers for real ones. Flip it on for real by filling in the two env vars; no code
changes needed, since both paths return the same `KeywordMetrics` shape.

This is the one place I knowingly deviated from "only real data" for the sake of a
runnable submission, and I'd rather be upfront about that than quietly fake it.

## AI tools used

This scaffold (models, agents, orchestrator, prompts, tests, README) was built with
Claude (Anthropic) as a coding assistant, reviewing and iterating on each piece
rather than accepting a single unreviewed generation. The pipeline's own agents use
Claude (`claude-sonnet-4-6`) by default via `ANTHROPIC_API_KEY`; swapping to
`LLM_PROVIDER=openai` uses GPT-4o instead with no other code changes, since both go
through the same `LLMClient.complete_json` interface.

## Other tradeoffs / known limitations

- **Synchronous pipeline** — `POST /profiles/<uuid>/run` runs all three agents
  in-request (per the spec, this is acceptable; expect 10–30s response times with
  ~15-20 queries). No Celery/background job queue is implemented.
- **No auth layer** — out of scope per the brief.
- **Rate limiting** — not implemented; would add via `Flask-Limiter` on the `/run`
  and `/recheck` endpoints in a real deployment.
- **Recheck vs. re-run** — `/queries/<uuid>/recheck` re-runs Agent 2 only, against
  the query's already-stored `query_intent`; it doesn't re-run Agent 1 or 3, by
  design (the assessment describes it as "re-run Agent 2").
