# Retrieval path audit — from raw query to account selection (deterministic pipeline, Qwen OFF)

Scope: `sidecar/chat_pipeline.py` over `personal_vault.core.search` (unchanged). Goal of this audit: stop patching word lists; make
*uncertainty* the default and let **only a small set of invariants** produce a confident (`exact`) answer.

## 1. The path (every step that can change which account is selected)
| # | Step | What it does | How it can turn uncertainty into a wrong confident answer |
|---|---|---|---|
| 0 | Input hygiene | NFC, strip invisible format chars (Cf), length cap, code-like syntax (`{ } < > $ \` \ \| ://`) rejected | split numbers (`1<ZWSP>1`), decomposed `ạ`, template strings read as numbers |
| 1 | `norm()` (core) | casefold, NFKD, strip accents, split digit/letter boundaries | **erases accent evidence** (`nhà`/`nha`, `hộp`/`họp`, `mở`/`mô`), splits `15a`→`15 a` |
| 2 | Injection phrases | known jailbreak phrasing → none | — |
| 3 | Follow-up router | ordinals / `máy N` / pronouns resolved **only inside the last result group** | markers lost when fillers are dropped, position-vs-identity clash, group truncated, a reference into a list of one re-confirming it, `mấy`≠`máy`, names read as ordinals |
| 4 | Negation split | `trừ …`, `không phải … mà …` → positive head + excluded items | excluded word dropped as filler; list items (`1 và 5`) |
| 5 | Filler removal (`_HARD`, `_SOFT`) | drops function/command words to expose the identity | **the dominant failure source**: a dropped word that was content (`nhà`, `Minh`, `a`) |
| 6 | Candidate queries | `prot` (keep vault-word fillers) / `hard` / `soft`; best rank wins | a weaker candidate beating a stricter one |
| 7 | `core.search` | exact identity → keyword subset (name/description/tags/url too) → fuzzy ≥0.76 | description/url hits via short words, shared-suffix fuzzy, accent-folded collisions |
| 8 | Post-filters | per-token fuzzy guard, short-word guard, accent-conflict guard, numeric identity filter | guard skipped on the `exact` branch (fixed) |
| 9 | Exclusion | remove entries matched by excluded items | partial exclusions |
| 10 | Status mapping + cap | core kind → `exact/ambiguous/suggested/none`; **exact gate** | — |

## 2. The invariants (what `exact` now means)
`status == "exact"` is produced only if **all** hold; otherwise the answer is a suggestion that the user must pick, or nothing:
1. **Unique basis** — exactly one entry has that identity string (no alias/name collision), and `suggested_action` exists only for such a single exact entry.
2. **Every dropped word is explained** — a word removed as filler is a *pure function word* (`_SAFE_DROP`), **or** there is no evidence it is content. Evidence = the word occurs in the vault's own vocabulary (identity, username, description, tags), is a single letter or a number, is capitalised mid-sentence (a name), or the user typed an accented variant of a non-function word. Unknown words therefore *lower confidence*; they never need a new stop-word entry.
3. **No accent conflict** — an accented query word and an entry that only has a *different* accented spelling of the same ASCII text (`hộp`/`họp`, `fb chỉnh`/`fb chính`) are not the same word. Accent-free typing stays compatible.
4. **No clash / multi-reference** — a bare number after a list is both a position and an identity (ask); several references in one turn are a choice; a reference into a list of one never re-confirms it; a missing machine number (`máy 2` when none exists) is *none*, not the 2nd result.
5. **Not code** — template/markup syntax is not a question.
Fuzzy, semantic and uncertain results are always `suggested` (or `ambiguous`); numeric identity is an exact token, never fuzzy.

## 3. What remains heuristic (honest list)
- `_SAFE_DROP` and the homograph handling (`nha`, `mo`, `ạ`/`a`) are language heuristics; they only *protect* now, they do not decide.
- Position-vs-identity for bare numbers is a UX policy (we ask), not a proof.
- Capitalisation is a weak signal (all-lowercase chat messages carry no name evidence).
- Recall is the price: abstain rate on the blind held-out is ~20 % (spelled-out numbers, small typos below the fuzzy threshold, "X hay Y" questions, chatty sentences with unknown words).

## 4. Evidence
`search_eval.py` (138 original + 5 red-team rounds), `heldout_eval.py` on a fixture locked by SHA-256 before the first run, `tests/test_search_reliability.py`.
