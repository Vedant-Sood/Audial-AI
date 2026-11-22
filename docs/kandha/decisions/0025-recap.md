# 0025 · "Summarise, then delete" is a redacted, extractive recap of the 5-minute memory, never saved

**Status.** Approved 22 Nov 2026; was proposed.

**Decision.**
- "What did I miss?" on the phone offers a recap: ≤ 5 sentences chosen by TF-IDF and recency
  from the caption memory.
- It is redacted with the shared spec.
- It is held in memory and wiped with the memory (at 300 s, and by off the record).
- It is never saved.

**Why.** This is the owner's idea ("summarises, then deletes the summary, auto-redacts")
mapped onto the summary's privacy design without adding anything that is kept.

**Rejected.** An on-device LLM summary for now. It is planned if a phone can run one within a
measured latency and battery budget.
