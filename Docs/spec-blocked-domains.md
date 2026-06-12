# Spec: Self-propagating blocked domains

## Background

Medium and similar paywalled domains can slip into the pipeline via HN results even though their RSS feeds are disabled. When NotebookLM fails to add every source in a batch the run fails entirely, and the current retry logic re-attempts anyway — wasting a NotebookLM credit.

## New file: `data/blocked_domains.json`

A JSON array of normalized domain strings (e.g. `["medium.com", "towardsdatascience.com"]`). Lives on the Docker data volume alongside `seen_urls.json`. Grows automatically at runtime; can be hand-edited to remove false positives.

**Malformed file behavior (read):** if the file exists but contains invalid JSON, log a warning and treat as empty — do not raise, do not overwrite.

**Malformed file behavior (write):** if the file exists but contains invalid JSON, log a warning and skip recording — do not overwrite a hand-edited file that may have a fixable typo.

---

## Domain normalization

All domain comparisons go through a single helper `_normalized_domain(url: str) -> str | None`:

1. `urlparse(url).hostname` — already lowercase, already strips port
2. Strip a leading `www.` prefix
3. Return `None` if the result is empty or `None`

**Matching is suffix-based:** blocking `medium.com` also blocks `foo.medium.com`. Check `domain == blocked or domain.endswith("." + blocked)`.

---

## Deterministic rejection predicate

A failure is a **deterministic rejection** if and only if `getattr(exc, "rpc_code", None) == 9`. This is the specific NotebookLM content-rejection code observed in production. Any other exception — including other `RPCError` codes, timeouts, auth errors, quota exhaustion, or network errors — is treated as transient.

---

## `pipeline/notebooklm_gen.py`

**1. New exception: `NoSourcesAddedError(RuntimeError)`**
Raised when every URL in a batch fails with a deterministic rejection. Exported so tests can import it.

**2. Per-URL failure tracking in `_generate_once`**
For each URL, categorize the failure:
- `rpc_code == 9` → deterministic; record the domain (see below) and add URL to `deterministic_failures`
- anything else → transient; add URL to `transient_failures`

**3. Exit condition when no sources were consumed**
After the URL loop, if `consumed` is empty:
- All failures were deterministic → `raise NoSourcesAddedError(...)`
- Any failure was transient → `raise RuntimeError("No sources could be added to the notebook")` (existing retryable behavior)

This ensures `NoSourcesAddedError` only fires when retrying is guaranteed to fail, and transient all-source failures keep the current retry semantics.

**4. Domain recording**
Only fires for deterministic rejections (`rpc_code == 9`). Load `data/blocked_domains.json`; if missing, start with `[]`; if malformed JSON, log a warning and skip (do not overwrite). Otherwise add the normalized domain if absent and write back. Swallow all other errors from this bookkeeping.

**5. No-retry guard**
Add `NoSourcesAddedError` alongside `ArtifactInProgressTimeoutError` in the no-retry raise.

**6. Empty-input edge case**
If `urls` is empty, no URL ever failed deterministically — raise `RuntimeError` (retryable), not `NoSourcesAddedError`. The precise rule: only raise `NoSourcesAddedError` when `deterministic_failures` is non-empty AND `transient_failures` is empty.

**Path:** module-level `_DEFAULT_BLOCKED = Path("data/blocked_domains.json")`. Add `blocked_domains_path: Path = _DEFAULT_BLOCKED` as an optional keyword-only parameter on both `_generate_once` and `generate_episode`; `generate_episode` passes it through to `_generate_once`. `pipeline.py` remains unchanged (uses the default).

---

## `pipeline/discovery.py`

`discover()` gains a `blocked_domains_path: Path` parameter (default `Path("data/blocked_domains.json")`). At the start of `discover()`, load the file into a `set[str]` (empty set if missing or malformed — log warning on malformed). After collecting all articles, filter out any whose normalized domain suffix-matches an entry in that set.

---

## Pinned URLs

Pinned URLs are injected in `run_pipeline()` after `discover()` and intentionally bypass the blocked-domains filter — the user explicitly pinned them. If a pinned URL's domain is in the blocked list it still proceeds to NotebookLM; if NotebookLM rejects it, the domain is recorded (same as any other URL) and the pin stays unconsumed. The user must remove the pin manually. This is intentional: pinned = explicit user override.

`pipeline.py` is unchanged.

---

## Tests

**`tests/test_notebooklm_gen.py`** — four new tests:
- `test_all_rpc9_raises_no_sources_no_retry` — all URLs fail with `rpc_code=9`; assert `NoSourcesAddedError` raised, `notebooks.create` called once (no retry), domain written to blocked file.
- `test_all_transient_raises_runtime_and_retries` — all URLs fail with a generic `RuntimeError`; assert `RuntimeError` raised (not `NoSourcesAddedError`), `notebooks.create` called twice (retried), domain NOT written.
- `test_mixed_rpc9_and_transient_raises_runtime_and_retries` — one URL fails with `rpc_code=9`, one with a transient error, none succeed; assert `RuntimeError` raised (not `NoSourcesAddedError`) and retried.
- `test_partial_rpc9_failure_records_domain_but_succeeds` — one URL fails with `rpc_code=9`, one succeeds; assert domain recorded, generation completes.

**`tests/test_discovery.py`** — two new tests:
- `test_blocked_domain_filtered_out` — write a `blocked_domains.json` with `medium.com`; return a `medium.com` article from the mock; assert it's absent from results.
- `test_blocked_domain_subdomain_filtered_out` — same but with a `subdomain.medium.com` URL; assert suffix matching works.

---

## What's not changing

- `pipeline.py` — no new parameter; `discover()` defaults its own path.
- Admin UI — the JSON file is the interface for now; no UI for managing blocked domains in scope.
