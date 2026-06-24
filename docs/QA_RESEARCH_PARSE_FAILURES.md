# Task 4 — JSONDecodeError failure modes for enc_10021 and enc_10036

**Source:** `runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl` lines 22 and 37, plus `src/ai_billing_audit/llm.py:168-171` (the existing fence-stripping patch).

## What the existing patch does and does not catch

`llm.py:168-171` strips a single ```json ... ``` (or ``` ... ```) fence using a non-greedy regex. This fixes the most common case where the model wraps a clean JSON object in a single code fence. The patch is silent on:

1. **Multiple fences** (e.g., reasoning + answer in two fences).
2. **Truncated responses** where the closing ``` is missing.
3. **Code blocks without the `json` tag** in the middle of a longer response.
4. **Empty/blank content** (which is what `Expecting value: line 1 column 1 (char 0)` actually means — `json.loads("")` raises this exact error).
5. **Mid-string breaks** (e.g., a JSON string cut off mid-escape).
6. **Prefix garbage** like `Sure! Here is the JSON:` before the object.

## What enc_10021 and enc_10036 actually returned

Both have `ok: false`, `error_type: "JSONDecodeError"`, `error_message: "Expecting value: line 1 column 1 (char 0)"`, and empty `summary`. The wall-clock times are 44s and 41s — both long, but within the 60s timeout.

`json.loads("")` raises exactly `Expecting value: line 1 column 1 (char 0)`. This means the parser reached `content.strip()` and got either an empty string, a string of only whitespace, or a string that started with a non-JSON character and the fence regex did not match. The most likely failure modes, ranked:

1. **Truncation at 4000 max_tokens.** Both runs are 41-44s, which is consistent with the model running close to its output budget. The model probably emitted reasoning + a partial JSON object, and the last token was cut off mid-string. The `fence_match` regex requires a closing ```, so on a truncated response it does not match, `content` stays as the raw text, and `json.loads(raw_text_with_unclosed_string)` raises — but the error message would be different ("Unterminated string" or similar), so this is less likely.
2. **Empty `content` from the LLM response.** `response["choices"][0]["message"]["content"]` came back as `None` or `""`. The `if content is not None` check at `llm.py:168` guards against `None` but not against `""`. The fence regex does not match an empty string, so `content` stays empty, and `json.loads("")` raises the observed error. This is the most likely cause.
3. **Reasoning-only response.** Some Ollama cloud models (especially when `minimax-m3:cloud` is in "thinking" mode) emit a long thinking trace and the final answer is on a separate channel (`message.reasoning` vs `message.content`). If litellm does not extract the final answer into `content` for this model, the response's `content` is empty.

## Recommended parser robustness

In `LLMClient.complete_json` (`src/ai_billing_audit/llm.py:128`), in order of priority:

1. **Guard against empty content** before the fence-strip step:
   ```python
   if not content or not content.strip():
       raise SchemaValidationError("LLM returned empty content (likely truncation or reasoning-only response)")
   ```
2. **Extract the first balanced JSON object** from the response as a fallback. Use `re.search(r'\{.*\}', content, re.DOTALL)` and then a `json.JSONDecoder().raw_decode()` call to find the first valid JSON start. This handles the "Sure! Here is the JSON: { ... }" prefix case and the "multiple fences with reasoning" case.
3. **Treat `response_format=json_schema` rejections as retryable.** When the provider's constrained decoding refuses (e.g., on an Ollama cloud model that doesn't honour the envelope), fall back to plain completion and run the heuristic extraction above. Currently the code makes one attempt and raises; a single retry on `SchemaValidationError` is cheap.
4. **Log the raw content (truncated) on parse failure** so the failure_modes analyzer can categorize truncation vs. empty vs. malformed. Add a `raw_response_excerpt` field to the error record in `run_7x.py:130-135`.

## Why this matters

2/50 = 4% parse failure rate. At 50-200 encounters/week per clinic, that's 2-8 wasted encounters/week plus a confused error log. After the prompt-fix to add `category`, parse failures will be a larger fraction of the residual error. Cheap fix, big UX win.

## Sources

- `src/ai_billing_audit/llm.py:128-179` (current `complete_json` implementation)
- `runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl:22,37` (the two errored records)
- `scripts/run_7x.py:115-138` (error capture — currently stores only `error_type` and `error_message[:500]`, not the raw response)
