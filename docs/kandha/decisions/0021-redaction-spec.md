# 0021 · Redaction is one deterministic spec with shared fixtures, implemented in Python and Kotlin

**Status.** Proposed.

**Decision.** `spec/redaction/` holds:
- the rules;
- `fixtures.jsonl`;
- the shared word lists (a name gazetteer, an allow-list, and street and clinical words).

The pipeline:
- spelled-out numbers are normalised first;
- regex + checksum (Verhoeff for Aadhaar, Luhn for cards) for numbers and IDs;
- for names: names the user typed, the gazetteer, honorific patterns and "my name is"
  patterns;
- speaker labels and tone are never written in the first place.

Clinical terms are redacted only when tied to a person (Q14).

Both implementations run the fixtures in CI. Precision and recall are reported per category
on a held-out set, and the known misses are listed.

**Why.**
- Both languages must give the same output offline. A deterministic pipeline is the only kind
  that guarantees that without shipping one model twice.
- It biases toward over-redaction, as the summary asks.

**Rejected.**
- spaCy or Presidio in Python only: no Kotlin parity.
- An LLM redactor: not deterministic, and heavy on a phone.

**Would change it.** Measured name recall < 0.95 → add one small ONNX NER model, run through
ONNX Runtime on both platforms.
