# Change report: music_rights_expire

**Type:** contract_update  
**Event:** The label notifies us that promo rights for 'Tense Beats' (music-02) end on 2026-10-20, before the campaign closes on 2026-11-30.  
**Changed entities:** music:music-02  
**Outcome:** Revised affected trailers

- Patched `contracts` ['music', {'track_id': 'music-02'}, 'expires']: `2026-12-31` -> `2026-10-20`

| Trailer | Impacted | Impacted segments | Segments touched | Clip changes | Status before | Status after | New version |
|---|---|---|---|---|---|---|---|
| family_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |
| young_adult_v1 | yes | young_adult_s01, young_adult_s02, young_adult_s03, young_adult_s04, young_adult_s05, young_adult_s06, young_adult_s07, young_adult_s08, young_adult_s09, young_adult_s10 | 10 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | young_adult_v2 |
| dialect_region_v1 | no | - | 0 | 0 | PASS_WITH_WARNINGS | PASS_WITH_WARNINGS | - |

All trailers were re-checked in full. 'Segments touched' counts any field change (e.g. a new music bed inherited by every segment); 'Clip changes' counts segments whose source clip was replaced, trimmed, added or removed.

## young_adult_v1

- `young_adult_s01` music: `music-02` -> `music-01`
- `young_adult_s02` music: `music-02` -> `music-01`
- `young_adult_s03` music: `music-02` -> `music-01`
- `young_adult_s04` music: `music-02` -> `music-01`
- `young_adult_s05` music: `music-02` -> `music-01`
- `young_adult_s06` music: `music-02` -> `music-01`
- `young_adult_s07` music: `music-02` -> `music-01`
- `young_adult_s08` music: `music-02` -> `music-01`
- `young_adult_s09` music: `music-02` -> `music-01`
- `young_adult_s10` music: `music-02` -> `music-01`
- `plan` bed_track: `music-02` -> `music-01`
- Why (swap_music): Music bed: music-02 ('Tense Beats') rights expire 2026-10-20, before campaign end 2026-11-30
- New warning: CRE-002 plan: Music bed music-01 (['melancholic', 'warm']) does not match the audience's intended moods ['driving', 'tense', 'upbeat']; no cleared track does
- New human approvals: editorial: music selection

