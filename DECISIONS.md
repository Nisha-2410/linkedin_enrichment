# Implementation decisions

- Distinct `search_role` values are assigned round numbers in first-seen order per company; a previously tried role keeps its original round and is idempotently skipped on re-upload.
- An `observations` table supplements the requested schema. It preserves per-round extraction evidence and enforces `(company, URL, search role)` idempotency while the `candidates` table remains one accumulated person per company.
- When accumulated observations conflict, positive match dimensions keep the strongest value; employment uses `current > unclear > former`; collision remains true only when every extracted observation indicates collision. This implements “upgrade, never downgrade.”
- At round four, one candidate at or above 85 is exported normally under `exhausted`; when nobody reaches 85, only the single best candidate above zero is selected and its CSV `low_confidence` field is set to `yes`.
- “Finalize early” is an export operation rather than a database mutation. It labels unresolved rows `needs_next_round (forced-finalized early)`, exports up to two current candidates at 85+, or one best-above-zero candidate explicitly marked low-confidence, so future uploads can still continue naturally.
- Candidate display names are derived from text before the first ` - ` in the LinkedIn result title because the input has no separate name field.
- The default model is `gemini-2.0-flash-lite`, kept in `backend/config.py` so it can be changed when free-tier availability changes.
