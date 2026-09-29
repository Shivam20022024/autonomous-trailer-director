# Change report: model_outage

**Type:** model_outage  
**Event:** The preferred language model (claude-opus-5-5) becomes unavailable after the plans are made.  
**Changed entities:** model:claude-opus-5-5  
**Outcome:** No existing plan depends on model availability; plans stand unchanged. Future planning uses claude-sonnet-5-5.


| Trailer | Impacted | Impacted segments | Segments touched | Clip changes | Status before | Status after | New version |
|---|---|---|---|---|---|---|---|
| family_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| young_adult_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| dialect_region_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |

All trailers were re-checked in full. 'Segments touched' counts any field change (e.g. a new music bed inherited by every segment); 'Clip changes' counts segments whose source clip was replaced, trimmed, added or removed.

## Model fallback

- Unavailable: claude-opus-5-5
- Remaining chain: claude-sonnet-5-5; next planning source: claude-sonnet-5-5

