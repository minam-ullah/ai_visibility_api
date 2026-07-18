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

flask db upgrade   # applies the migration in migrations/versions/, creates all 4 tables
python run.py
# API is now on http://localhost:5000
```

Run the tests: `pytest tests/ -v`

### Setup via Docker Compose (bonus)

```bash
cp .env.example .env   # set your LLM API key
docker-compose up --build
# then, in a second terminal:
docker-compose exec api flask db upgrade
```

This starts the API on `:5000` backed by a Postgres container. Comment out the `db`
service and the `DATABASE_URL` override in `docker-compose.yml` if you'd rather keep
SQLite.

### Migrations

A real Alembic migration (`migrations/versions/..._initial_schema.py`) is committed
and generates all four tables (`business_profiles`, `pipeline_runs`,
`discovered_queries`, `content_recommendations`) plus the `domain` index. Apply it
with `flask db upgrade`. If you change a model, generate the next migration the
normal way:

```bash
flask db migrate -m "describe the change"
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
│   ├── base.py             # shared LLM-call plumbing (BaseAgent.ask)
│   ├── discovery.py         # Agent 1 - Query Discovery
│   ├── scoring.py             # Agent 2 - Visibility Scoring
│   └── recommendation.py       # Agent 3 - Content Recommendation
├── services/
│   ├── llm_client.py             # Anthropic/OpenAI wrapper: JSON extraction + one repair retry
│   ├── search_data.py              # real keyword data (DataForSEO) with a documented mock fallback
│   └── pipeline.py                   # orchestrator: Agent1 -> Agent2 (per-query, failure-isolated) -> Agent3
├── api/
│   ├── profiles.py                    # /profiles, /profiles/<id>/run, /queries, /recommendations
│   └── queries.py                      # /queries/<id>/recheck
└── utils/
    ├── errors.py                        # APIError + consistent JSON error responses
    ├── scoring.py                        # opportunity score formula
    ├── schemas.py                         # marshmallow request validation schemas
    ├── limiter.py                          # Flask-Limiter singleton
    └── logging_config.py                    # request_id + pipeline run_uuid correlation IDs
migrations/               # Alembic migration history (flask db upgrade to apply)
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

Built in Cursor, my day-to-day IDE for work. AI assistance was used as follows:
ChatGPT helped resolve the initial project directory/file structure; both Claude and
ChatGPT were used to check syntax and evaluate the best fix in each case during
development. The pipeline's own agents use Claude (`claude-sonnet-4-6`) by default
via `ANTHROPIC_API_KEY`; swapping to `LLM_PROVIDER=openai` uses GPT-4o instead with
no other code changes, since both go through the same `LLMClient.complete_json`
interface.

## Other tradeoffs / known limitations

- **Synchronous pipeline** — `POST /profiles/<uuid>/run` runs all three agents
  in-request (per the spec, this is acceptable; expect 10–30s response times with
  ~15-20 queries). No Celery/background job queue is implemented.
- **No auth layer** — out of scope per the brief.
- **Recheck vs. re-run** — `/queries/<uuid>/recheck` re-runs Agent 2 only, against
  the query's already-stored `query_intent`; it doesn't re-run Agent 1 or 3, by
  design (the assessment describes it as "re-run Agent 2").

## Bonus items implemented

- **Rate limiting** (`Flask-Limiter`, `app/utils/limiter.py`) — `POST
  /profiles/<uuid>/run` is capped at 5/min and `POST /queries/<uuid>/recheck` at
  10/min per client IP, both returning the same `{"error": {...}}` shape as every
  other endpoint (`RATE_LIMITED`, HTTP 429). Uses in-memory storage, which is fine
  for a single-process eval deployment; a real multi-worker deployment should point
  `Limiter(storage_uri=...)` at Redis so limits are shared across workers.
- **Request/response validation** (`marshmallow`, `app/utils/schemas.py`) —
  `POST /profiles` is validated against `CreateProfileSchema` (required fields,
  types, string length limits) instead of hand-rolled `if` checks. Validation
  failures return `422 VALIDATION_ERROR` with a `details` object containing
  per-field messages.
- **Structured logging with correlation IDs** (`app/utils/logging_config.py`) —
  every HTTP request gets a `request_id` (from the `X-Request-ID` header if the
  caller sent one, otherwise generated) that's attached to every log line for that
  request and echoed back in the response header. Separately, every pipeline run
  gets its own `run_uuid` prefix on all of its log lines (spanning all three
  agents), via a `LoggerAdapter` created in `run_pipeline()` — so a single run's
  full trace can be grepped out of shared logs even under concurrent traffic.
- **Docker Compose** — see "Setup" above.
- **Unit tests for agent logic** — see "AI tools used" / `tests/test_agents.py`
  (12 tests: 3 agents + validation schema + opportunity formula).
