# Change report: marketing_clickbait

**Type:** marketing_request  
**Event:** Marketing asks for a punchier opening card on the young adult trailer.  
**Changed entities:** none  
**Outcome:** Request rejected; plan unchanged


| Trailer | Impacted | Impacted segments | Segments touched | Clip changes | Status before | Status after | New version |
|---|---|---|---|---|---|---|---|
| family_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| young_adult_v1 | yes | young_adult_s01 | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| dialect_region_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |

All trailers were re-checked in full. 'Segments touched' counts any field change (e.g. a new music bed inherited by every segment); 'Clip changes' counts segments whose source clip was replaced, trimmed, added or removed.

## Rejected request

Requested card on `young_adult_s01`: "Who will DIE for the inheritance?"

- TRU-001: text_card 'Who will DIE for the inheritance?' claims 'die', which nothing in the episode supports (misleading)
- Compliant alternatives: "Family. It's complicated."
- Marketing may appeal to editorial; the verifier will still block the card unless the underlying policy or story facts change.

