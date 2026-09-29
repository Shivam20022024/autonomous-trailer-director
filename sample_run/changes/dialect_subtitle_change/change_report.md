# Change report: dialect_subtitle_change

**Type:** subtitle_update  
**Event:** The localisation vendor redelivers Dialect A. Dadi now addresses Bebe as 'Bahu' (daughter-in-law) instead of 'Beti', which changes their relationship.  
**Changed entities:** cue:dialect_a:d08_1  
**Outcome:** Revised affected trailers

- Patched `subtitles` ['cues', 'dialect_a', 'd08_1']: `Beti, you carry this whole house on your shoulders.` -> `Bahu, you carry this whole house on your shoulders.`

| Trailer | Impacted | Impacted segments | Segments touched | Clip changes | Status before | Status after | New version |
|---|---|---|---|---|---|---|---|
| family_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| young_adult_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| dialect_region_v1 | yes | dialect_region_s06 | 1 | 1 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | dialect_region_v2 |

All trailers were re-checked in full. 'Segments touched' counts any field change (e.g. a new music bed inherited by every segment); 'Clip changes' counts segments whose source clip was replaced, trimmed, added or removed.

## dialect_region_v1

- `dialect_region_s06` source_ref: `line:d08_1` -> `line:d08_2`
- `dialect_region_s06` source_in: `00:09:30.750` -> `00:09:35.950`
- `dialect_region_s06` source_out: `00:09:35.850` -> `00:09:40.350`
- `dialect_region_s06` subtitle_text: `Beti, you carry this whole house on your shoulders.` -> `Someone has to, Dadi.`
- Why (reground): SRC-006: Subtitle for 'd08_1' does not match track 'dialect_a'
- Why (replace_clip): TRU-002: Subtitle dialect_a:d08_1 addresses bebe as 'bahu' (daughter_in_law), but the story map says bebe is dadi's granddaughter

