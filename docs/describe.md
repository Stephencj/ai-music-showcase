# Describe your song (and revise it)

`POST /api/describe {"text": "..."}` turns a plain-English description into a
**song plan**: the body of a `POST /api/generate` request (genre, key, tempo,
sections, instruments, Funk Fusion arrangement variants, lead voice, hits,
loudness). `POST /api/revise {"plan": {...}, "feedback": "..."}` applies
plain-English feedback ("the bass is doing too much", "no stabs",
"background level") to a plan. Both return:

```
{"plan": {...}, "summary": "...", "understood": ["chips"], "notes": [...],
 "interpreter": "claude" | "local" | "rules", "engine": "funk_fusion" | "compose_song",
 "attempts": [...], "changes": [...] /* revise only */}
```

Add `"wait": false` to get `{"job_id"}` and poll `/api/jobs/{id}` instead
(the web app does this).

## Who interprets

1. **Claude**, through the AI request queue, when an answerer is polling it.
   The app skips Claude at once when no answerer has polled in the last
   30 s, and gives up if nobody claims the request within 20 s
   (`AI_MUSIC_CLAIM_TIMEOUT`).
2. **The local model** (MLX Qwen through the gateway at
   `AI_MUSIC_LOCAL_AI_URL`, default `http://127.0.0.1:8800`).
3. **The rules** (`nl_parser` + `song_plan.FEEDBACK_RULES`).

What the options mean and the producer's taste live in ONE file,
`src/composition/song_plan_guide.md`. Both Claude and the local model get it
(plus the live genre/instrument catalog) as their system prompt; every answer
is validated by `song_plan.normalize_plan`, so a bad answer falls through to
the next interpreter instead of failing. To force a path (testing):
`AI_MUSIC_INTERPRETERS=local,rules`.

## Starting the Claude answerer

From the repo, while the app runs:

```sh
.venv/bin/python scripts/claude_answerer.py            # answers the live app on :7860
```

It polls `/api/ai/requests?status=pending&kind=describe,revise`, claims each
request, runs one headless `claude -p` turn (your Claude login; no tools, no
MCP servers) and posts the plan back. Stop it with Ctrl-C; Describe then
falls back to the local model. Options: `--model sonnet`, `--api URL`,
`--once`.

### Or from an interactive Claude Code session

Paste this into a Claude Code session in the repo:

> Every few seconds, GET http://127.0.0.1:7860/api/ai/requests?status=pending&kind=describe,revise&answerer=session.
> For each request: POST /api/ai/requests/{id}/claim?answerer=session (skip it on 409),
> then follow `params.system` as your instructions and answer `params.user`.
> POST /api/ai/requests/{id}/answer with `{"answer": {"plan": {...}, "summary": "..."}}`.
> Keep going until I say stop.

## In the app: Create

The web app's **Create** tab is built on these two calls. The Session view is
a thread: your description → "Here's what I understood" + v1; plain-English
feedback (or the quick chips: Quieter, Simpler bass, Bigger chorus, Slower) →
"Changed N things" + the next version, always with v1's seed so only what you
asked for changes. Versions can be compared A/B and saved to the library.
The Timeline view shows the version's sections across and its parts down
(what each part plays, from the arrangement variants and
`section_overrides`); a section's option chips edit
`section_overrides.<role>.arrangement` and "Regenerate" re-renders with the
same seed. "Add block" splits the version into section blocks, inserts a
saved block and opens it in Blocks. A voice note goes through
`POST /api/transcribe` (the gateway's `/transcribe_upload`). The thread is
kept in the browser (localStorage `aimusic.create.session`). The full
Generate form ("Advanced form") and the block builder ("Blocks") are in
Create's ⋯ menu.
