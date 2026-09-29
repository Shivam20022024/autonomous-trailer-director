"""Builds dashboard.html: a single offline HTML file that visualises a run directory.

No server, no external scripts or fonts: the run's JSON outputs are embedded in the page.
"""
import json
from pathlib import Path

from .timecode import parse_tc


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def collect(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    summary = _load(run_dir / "run_summary.json") or {}
    story = _load(run_dir / "story_map.json") or {}
    scenes = [{"id": s["scene_id"], "title": s["title"], "start": parse_tc(s["start"]), "end": parse_tc(s["end"]),
               "tags": s["tags"]} for s in story.get("scene_index", [])]
    trailers = {}
    for aud in summary.get("trailers", {}):
        t = _load(run_dir / f"{aud}_trailer.json")
        if t:
            trailers[aud] = t
    log_path = run_dir / "decision_log.jsonl"
    log = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []
    changes = []
    for rep in sorted((run_dir / "changes").glob("*/change_report.json")):
        changes.append(_load(rep))
    constraints = _load(run_dir / "constraint_map.json") or {}
    return {"run_dir": run_dir.name, "summary": summary, "story": story, "spoilers": _load(run_dir / "spoiler_map.json") or {},
            "insights": _load(run_dir / "audience_insight_review.json") or {}, "scenes": scenes,
            "episode_end": max((s["end"] for s in scenes), default=1), "trailers": trailers, "log": log,
            "changes": changes, "rules": len(constraints.get("rules", [])),
            "eligibility": constraints.get("scene_eligibility", {})}


def build_dashboard(run_dir) -> Path:
    data = json.dumps(collect(run_dir), ensure_ascii=False).replace("</", "<\\/")
    out = Path(run_dir) / "dashboard.html"
    out.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trailer Director dashboard</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1c2230;--muted:#5f6b7a;--line:#e3e6eb;--accent:#2f5bd3;
--ok:#1e8a4c;--okbg:#e6f4ec;--warn:#9a6700;--warnbg:#fff4d6;--bad:#c62828;--badbg:#fde8e8;--spoil:#d32f2f;
--b1:#4c6ef5;--b2:#12b886;--b3:#f59f00;--b4:#e64980;--b5:#7950f2;--b6:#15aabf;--b7:#82c91e}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--panel:#1b2029;--ink:#e6e9ef;--muted:#9aa4b2;--line:#2c333f;--accent:#7c9cff;
--ok:#5fd08f;--okbg:#16301f;--warn:#f2c14e;--warnbg:#332a12;--bad:#ff7b7b;--badbg:#3a1a1a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:18px 24px 0;display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between}
h1{font-size:20px;margin:0}h2{font-size:16px;margin:22px 0 10px}h3{font-size:14px;margin:16px 0 8px}
.muted{color:var(--muted)}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
nav{display:flex;gap:4px;padding:12px 24px 0;border-bottom:1px solid var(--line);overflow-x:auto}
nav button{background:none;border:0;border-bottom:2px solid transparent;padding:8px 12px;color:var(--muted);font:inherit;cursor:pointer;white-space:nowrap}
nav button.on{color:var(--ink);border-color:var(--accent);font-weight:600}
main{padding:8px 24px 40px;max-width:1400px}section{display:none}section.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card.click{cursor:pointer}.card.click:hover{border-color:var(--accent)}
.kpi{font-size:22px;font-weight:650}.row{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600}
.PASS{background:var(--okbg);color:var(--ok)}.PASS_WITH_WARNINGS{background:var(--warnbg);color:var(--warn)}.FAIL{background:var(--badbg);color:var(--bad)}
.meter{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:6px}.meter>i{display:block;height:100%;background:var(--accent)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted);font-weight:600;background:var(--bg)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}
.tl{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:8px;margin:6px 0 30px}
.tl .sc{position:absolute;top:0;bottom:0;border-right:1px dashed var(--line)}
.tl .sc span{position:absolute;bottom:-17px;left:2px;font-size:10px;color:var(--muted);white-space:nowrap}
.tl .sp{position:absolute;top:0;bottom:0;background:repeating-linear-gradient(45deg,rgba(211,47,47,.28) 0 5px,rgba(211,47,47,.1) 5px 10px);border-left:1px solid var(--spoil);border-right:1px solid var(--spoil)}
.tl .clip{position:absolute;height:18px;min-width:14px;border-radius:4px;color:#fff;font-size:10px;font-weight:700;box-shadow:0 0 0 1.5px var(--panel);display:flex;align-items:center;justify-content:center}
.seq{display:flex;height:34px;border-radius:8px;overflow:hidden;border:1px solid var(--line);margin:6px 0 4px}
.seq div{min-width:0;color:#fff;font-size:11px;display:flex;align-items:center;padding:0 6px;border-right:1px solid rgba(255,255,255,.4)}.seq div span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
ul.plain{margin:0;padding-left:18px}li{margin:3px 0}
.pill.beat{white-space:normal;max-width:150px;line-height:1.3;padding:2px 6px}
.pill{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:0 6px;margin:1px 2px 1px 0;font-size:11.5px}
.err{color:var(--bad)}.wrn{color:var(--warn)}.good{color:var(--ok)}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.flex{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
</style></head><body>
<header><div><h1 id="title"></h1><div class="muted" id="sub"></div></div><div class="muted mono" id="runinfo"></div></header>
<nav id="tabs"></nav><main id="main"></main>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const $ = s => document.querySelector(s);
const BEATS = ["--b1","--b2","--b3","--b4","--b5","--b6","--b7"];
const beatColour = (() => { const m = {}; return b => m[b] ??= `var(${BEATS[Object.keys(m).length % BEATS.length]})`; })();
const tc = s => { const [h,m,r] = s.split(":"); return (+h)*3600 + (+m)*60 + parseFloat(r); };
const pct = t => (100 * t / D.episode_end).toFixed(3) + "%";
const badge = s => `<span class="badge ${esc(s)}">${esc(s.replaceAll("_"," "))}</span>`;
const auds = Object.keys(D.trailers);

$("#title").textContent = `Trailer Director: ${D.story.title || ""}`;
$("#sub").textContent = `${D.story.episode_id || ""} · ${D.scenes.length} scenes · ${D.rules} constraint rules · run folder ${D.run_dir}`;
$("#runinfo").textContent = `run ${D.summary.run_id} · mode ${D.summary.mode}`;

const tabs = [["overview","Overview"], ...auds.map(a => [a, D.trailers[a].audience]), ["story","Story & spoilers"],
  ["changes",`Changes (${D.changes.length})`], ["log",`Decision log (${D.log.length})`]];
$("#tabs").innerHTML = tabs.map(([id,l]) => `<button data-t="${id}">${esc(l)}</button>`).join("");
$("#main").innerHTML = tabs.map(([id]) => `<section id="s-${id}"></section>`).join("");
function show(id){ document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("on",b.dataset.t===id));
  document.querySelectorAll("section").forEach(s=>s.classList.toggle("on",s.id==="s-"+id)); try{localStorage.setItem("td-tab",id); history.replaceState(null,"","#"+id)}catch(e){} }
document.querySelectorAll("nav button").forEach(b => b.onclick = () => show(b.dataset.t));

function timeline(t){
  const sc = D.scenes.map(s => `<div class="sc" style="left:${pct(s.start)};width:calc(${pct(s.end-s.start)})" title="${esc(s.id+': '+s.title)}"><span>${esc(s.id.replace("scene_","S"))}</span></div>`).join("");
  const sp = (D.spoilers.protected_facts||[]).flatMap(f => f.protected_ranges.map(r =>
    `<div class="sp" style="left:${pct(tc(r.start))};width:${pct(tc(r.end)-tc(r.start))}" title="${esc('Protected: '+f.statement+' ('+r.ref+')')}"></div>`)).join("");
  // Markers are at least 14px wide, so clips close together would overlap: put them in separate lanes.
  const gap = D.episode_end * 0.02, lanes = [];
  const placed = (t ? [...t.segments] : []).sort((a,b) => tc(a.source_in) - tc(b.source_in)).map(s => {
    const a = tc(s.source_in), b = Math.max(tc(s.source_out), a + gap);
    let lane = lanes.findIndex(end => end <= a); if (lane < 0) { lane = lanes.length; lanes.push(0); }
    lanes[lane] = b; return [s, lane]; });
  const clips = placed.map(([s, lane]) => `<div class="clip" style="top:${6 + lane*22}px;left:${pct(tc(s.source_in))};width:${pct(tc(s.source_out)-tc(s.source_in))};background:${beatColour(s.beat)}" title="${esc('#'+s.order+' '+s.beat+': '+s.source_in+'-'+s.source_out)}">${s.order}</div>`).join("");
  return `<div class="tl" style="height:${12 + Math.max(1, lanes.length)*22}px">${sc}${sp}${clips}</div>`;
}
function sequence(t){
  const total = t.segments.reduce((a,s)=>a+(s.duration_seconds||0),0) || 1;
  return `<div class="seq">${t.segments.map(s=>`<div style="flex:${s.duration_seconds||0.1};background:${beatColour(s.beat)}" title="${esc(s.order+'. '+s.beat+' · '+s.duration_seconds+'s · '+s.reason)}"><span>${s.order} ${esc(s.beat)}</span></div>`).join("")}</div>
  <div class="muted" style="font-size:12px">Trailer order, width = clip length (${total.toFixed(1)}s total)</div>`;
}

// ---- overview
(() => {
  const b = D.summary.budget || {};
  const cards = auds.map(a => { const t = D.trailers[a], v = t.validation;
    return `<div class="card click" data-go="${a}"><div style="display:flex;justify-content:space-between;gap:8px"><b>${esc(t.audience)}</b>${badge(v.status)}</div>
    <div class="muted" style="margin:6px 0 8px">“${esc(t.audience_promise)}”</div>
    <div class="row"><div><div class="kpi">${t.duration_seconds}s</div><div class="muted">target ${t.target_duration_seconds.join("-")}s</div></div>
    <div><div class="kpi">${t.segments.length}</div><div class="muted">clips</div></div>
    <div><div class="kpi">${t.repair_history.length}</div><div class="muted">repairs</div></div>
    <div><div class="kpi">${v.warnings.length}</div><div class="muted">warnings</div></div>
    <div><div class="kpi">$${t.cost.estimated_usd.toFixed(3)}</div><div class="muted">est. cost</div></div></div>
    <div style="margin-top:8px">${t.ready_for_editor ? '<span class="good">Ready for editor</span>' : '<span class="err">Not ready: unresolved errors</span>'} ·
    <span class="muted">${t.human_approvals_required.length} human approvals</span></div></div>`; }).join("");
  const m = (v, max) => `<div class="meter"><i style="width:${Math.min(100, 100*v/max)}%"></i></div>`;
  const dist = (D.summary.distinctness||[]).map(r => `<li>${esc(r.pair.join(" vs "))}: ${r.shared_clips} shared clips (Jaccard ${r.jaccard})${r.too_similar?' <b class="err">too similar</b>':''}</li>`).join("");
  const counts = {}; D.log.forEach(e => counts[e.kind] = (counts[e.kind]||0)+1);
  const k = (id, label) => `<li><b>${counts[id]||0}</b> ${label}</li>`;
  $("#s-overview").innerHTML = `<h2>Trailers</h2><div class="grid">${cards}</div>
  <h2>Where each trailer's clips come from</h2>
  <div class="legend"><span><i style="background:repeating-linear-gradient(45deg,rgba(211,47,47,.5) 0 3px,rgba(211,47,47,.15) 3px 6px)"></i>protected story fact (never shown)</span><span>numbers = trailer order, colour = beat</span></div>
  ${auds.map(a => `<h3>${esc(D.trailers[a].audience)}</h3>${timeline(D.trailers[a])}`).join("")}
  <div class="grid" style="margin-top:6px">
   <div class="card"><b>Budget</b><div class="row"><div style="flex:1">Model calls ${b.model_calls}/${b.max_model_calls}${m(b.model_calls,b.max_model_calls)}</div>
   <div style="flex:1">Cost $${(b.estimated_usd||0).toFixed(3)}/$${b.max_total_usd}${m(b.estimated_usd,b.max_total_usd)}</div>
   <div style="flex:1">Media ${b.media_minutes}/${b.max_media_minutes} min${m(b.media_minutes,b.max_media_minutes)}</div></div></div>
   <div class="card"><b>What the safety layer stopped</b><ul class="plain">
    ${k("hallucination_rejected","invented scenes rejected")}${k("high_performing_idea_rejected","high-scoring spoiler ideas rejected")}
    ${k("claim_rejected","unsupported model claims rejected")}${k("insight_excluded","biased audience insights excluded")}
    ${k("injection_flag","instruction-like text ignored")}${k("repair","repairs applied")}</ul></div>
   <div class="card"><b>Distinctness</b><ul class="plain">${dist}</ul></div></div>`;
  document.querySelectorAll("[data-go]").forEach(c => c.onclick = () => show(c.dataset.go));
})();

// ---- per-trailer
auds.forEach(a => { const t = D.trailers[a], v = t.validation;
  const rows = t.segments.map(s => `<tr><td>${s.order}</td><td><span class="pill beat" style="background:${beatColour(s.beat)};color:#fff;border:0">${esc(s.beat)}</span></td>
   <td class="mono">${esc(s.video)}<br><span class="muted">${esc(s.source_ref||"")}</span></td><td class="mono">${esc(s.source_in)}<br>${esc(s.source_out)}</td>
   <td>${esc(s.audio)}${s.music?`<br><span class="muted">${esc(s.music)}</span>`:""}</td>
   <td>${s.subtitle?`<span class="muted">[${esc(s.subtitle.track)}]</span> ${esc(s.subtitle.text)}`:'<span class="muted">-</span>'}</td>
   <td>${s.text_card?`“${esc(s.text_card.text)}” <span class="muted">${s.text_card.seconds}s</span>`:'<span class="muted">-</span>'}</td>
   <td>${esc(s.reason)}<div>${s.evidence.map(e=>`<span class="pill mono">${esc(e)}</span>`).join("")}</div></td></tr>`).join("");
  const rep = t.repair_history.map(r => { const ft = r.from!==undefined||r.to!==undefined;
    const fmt = x => typeof x === "object" && x ? `${x.video||""} ${x.source_ref||""} ${x.audio||""}${x.subtitle_track?" ["+x.subtitle_track+"]":""}${x.text_card?" “"+x.text_card+"”":""}` : x;
    return `<tr><td>${r.round}</td><td><b>${esc(r.action)}</b></td><td class="mono">${esc(r.segment_id||"plan")}</td>
    <td>${ft?`<span class="muted">${esc(fmt(r.from))}</span> → ${esc(fmt(r.to))}`:esc(r.insight||"")}</td><td>${r.because.map(esc).join("<br>")}</td></tr>`; }).join("");
  const finding = f => `<li><span class="mono">${esc(f.check_id)}</span> <span class="muted">${esc(f.segment_id||"plan")}</span> ${esc(f.message)}</li>`;
  $("#s-"+a).innerHTML = `<div class="flex" style="margin-top:16px">${badge(v.status)} <b>${esc(t.trailer_id)}</b>
   <span class="muted">${t.duration_seconds}s · ${t.segments.length} clips · music ${esc(t.music_plan.bed_track)} · planned by ${esc(t.planning_source.proposal)} (${esc(t.planning_source.model)})</span></div>
   <div class="grid"><div class="card"><b>Promise</b><div>“${esc(t.audience_promise)}”</div><div class="muted" style="margin-top:6px">${esc(t.objective)}</div></div>
   <div class="card"><b>Emotional journey</b><div>${t.emotional_journey.map(esc).join(" → ")}</div><div class="muted" style="margin-top:6px">Insights used: ${esc(t.insights_used.join(", ")||"none")}</div></div>
   <div class="card"><b>Music</b><div>${esc(t.music_plan.bed_track)}</div><div class="muted" style="margin-top:6px">${esc(t.music_plan.reason)}</div></div></div>
   <h2>Structure</h2>${sequence(t)}<h3>Source positions in the episode</h3>${timeline(t)}
   <h2>Edit decision list</h2><div class="wrap"><table><tr><th>#</th><th>Beat</th><th>Source</th><th>In / out</th><th>Audio</th><th>Subtitle</th><th>Text card</th><th>Reason and evidence</th></tr>${rows}</table></div>
   ${v.errors.length?`<h2 class="err">Unresolved errors: plan rejected</h2><ul>${v.errors.map(finding).join("")}</ul>`:""}
   <h2>Repairs (${t.repair_history.length})</h2>${rep?`<div class="wrap"><table><tr><th>Round</th><th>Action</th><th>Segment</th><th>Change</th><th>Because</th></tr>${rep}</table></div>`:'<div class="muted">No repairs were needed.</div>'}
   <div class="grid" style="margin-top:14px"><div class="card"><b class="wrn">Warnings (${v.warnings.length})</b><ul class="plain">${v.warnings.map(finding).join("")||"<li>none</li>"}</ul></div>
   <div class="card"><b>Human approvals required</b><ul class="plain">${t.human_approvals_required.map(h=>`<li><span class="pill">${esc(h.owner)}</span>${esc(h.approval)}${h.segments.length?` <span class="muted">(${esc(h.segments.join(", "))})</span>`:""}</li>`).join("")}</ul></div>
   <div class="card"><b>Cost</b><div class="kpi">$${t.cost.estimated_usd.toFixed(4)}</div><ul class="plain">${t.cost.lower_cost_fallback.map(f=>`<li>${esc(f.strategy)}: $${f.estimated_usd.toFixed(4)}</li>`).join("")}</ul></div></div>`;
});

// ---- story & spoilers
(() => { const s = D.story, sp = D.spoilers;
  const facts = (sp.protected_facts||[]).map(f => `<li><b>${esc(f.fact_id)}</b> <span class="pill">${esc(f.source)}</span> ${esc(f.statement)}
    <div class="muted mono">${f.protected_ranges.map(r=>esc(r.ref+" "+r.start+"-"+r.end)).join(" · ")}</div>
    ${f.forbidden_sequences.length?`<div class="muted">Forbidden cut orders: ${esc(f.forbidden_sequences.map(x=>x.join(" → ")).join("; "))}</div>`:""}</li>`).join("");
  const rel = (s.relationships||[]).map(r => `<span class="pill">${esc(r.to)} is ${esc(r.from)}'s ${esc(r.relation)}</span>`).join("");
  const rej = (s.rejected_model_claims||[]).map(r => `<li><span class="pill">${esc(r.kind)}</span>${esc(JSON.stringify(r.claim).slice(0,160))} <div class="err">${esc(r.reason)}</div></li>`).join("");
  const mism = (s.description_mismatches||[]).map(m => `<li>${esc(m.scene_id)}: “${esc(m.term)}” only in the ${m.in_ai_description?"AI":"human"} description → treated as ${esc(m.implied_tag)}</li>`).join("");
  const inj = (s.untrusted_text_flags||[]).map(f => `<li>${esc(f.scene_id)} <span class="mono">${esc(f.field)}</span>: <span class="muted">${esc(f.excerpt)}</span></li>`).join("");
  const ins = Object.entries(D.insights).flatMap(([a,rows]) => rows.map(r => `<tr><td>${esc(a)}</td><td class="mono">${esc(r.insight_id)}</td><td>${esc(r.claim)}</td>
    <td>${r.usable?'<span class="good">usable</span>':`<span class="err">excluded</span><div class="muted">${r.flags.map(esc).join("<br>")}</div>`}</td></tr>`)).join("");
  const elig = Object.keys(D.eligibility).length ? `<h2>Scene eligibility by audience</h2><div class="wrap"><table><tr><th>Scene</th>${Object.keys(D.eligibility).map(a=>`<th>${esc(a)}</th>`).join("")}</tr>
    ${D.scenes.map(sc=>`<tr><td>${esc(sc.id)} <span class="muted">${esc(sc.title)}</span></td>${Object.keys(D.eligibility).map(a=>{const e=D.eligibility[a][sc.id]||{};
      const c={blocked:"err",restricted:"wrn",caution:"wrn",open:"good"}[e.status]||"";return `<td><b class="${c}">${esc(e.status||"")}</b><div class="muted mono" style="font-size:11px">${esc((e.rules||[]).join(" "))}</div></td>`}).join("")}</tr>`).join("")}</table></div>` : "";
  $("#s-story").innerHTML = `<h2>Protected story facts</h2><div class="muted">Coverage: ${esc(sp.coverage||"")}. Red zones on the timeline are never shown in any trailer.</div>${timeline(null)}<ul>${facts}</ul>
   <h2>Verified relationships (${(s.relationships||[]).length})</h2><div>${rel||'<span class="muted">none verified</span>'}</div>
   <div class="grid" style="margin-top:14px"><div class="card"><b class="err">Model claims rejected (${(s.rejected_model_claims||[]).length})</b><ul class="plain">${rej||"<li>none</li>"}</ul></div>
   <div class="card"><b class="wrn">Description mismatches</b><ul class="plain">${mism||"<li>none</li>"}</ul></div>
   <div class="card"><b class="wrn">Instruction-like text ignored</b><ul class="plain">${inj||"<li>none</li>"}</ul></div></div>
   <h2>Audience insight review</h2><div class="wrap"><table><tr><th>Audience</th><th>Insight</th><th>Claim</th><th>Verdict</th></tr>${ins}</table></div>${elig}`;
})();

// ---- changes
(() => { if (!D.changes.length) { $("#s-changes").innerHTML = `<p class="muted">No change events applied. Try: <span class="mono">python run_director.py change --event events/music_rights_expire.json</span></p>`; return; }
  $("#s-changes").innerHTML = D.changes.map(c => `<div class="card" style="margin-top:14px"><div class="flex"><b>${esc(c.event_id)}</b><span class="pill">${esc(c.type)}</span><span class="muted">${esc(c.outcome)}</span></div>
   <div>${esc(c.description)}</div><div class="muted mono" style="margin:6px 0">changed: ${esc(c.changed_entities.join(", ")||"none")}</div>
   <div class="wrap"><table><tr><th>Trailer</th><th>Impacted</th><th>Impacted segments</th><th>Segments touched</th><th>Clip changes</th><th>Status after</th><th>New version</th></tr>
   ${c.trailers.map(t=>`<tr><td>${esc(t.trailer_id)}</td><td>${t.impacted?'<b>yes</b>':'<span class="muted">no</span>'}</td><td class="mono">${esc((t.impacted_segments||[]).join(", ")||"-")}</td>
    <td>${t.changed_segments}</td><td>${t.clip_changes??0}</td><td>${badge(t.status_after)}</td><td>${esc(t.new_trailer_id||"-")}</td></tr>`).join("")}</table></div>
   ${c.trailers.flatMap(t=>(t.repair_actions||[]).map(r=>`<div style="margin-top:6px"><b>${esc(r.action)}</b> ${esc(r.segment_id||"plan")}: <span class="muted">${esc(r.because.join("; "))}</span></div>`)).join("")}
   ${c.trailers.flatMap(t=>(t.new_warnings||[]).map(w=>`<div class="wrn" style="margin-top:4px">New warning: ${esc(w)}</div>`)).join("")}
   ${c.rejection?`<div class="err" style="margin-top:8px">Rejected: “${esc(c.rejection.requested.text)}”: ${esc(c.rejection.violations.map(v=>v.message).join("; "))}</div>
     ${c.rejection.compliant_alternatives?.length?`<div class="good">Compliant alternatives: ${esc(c.rejection.compliant_alternatives.map(a=>a.text).join(" / "))}</div>`:""}`:""}</div>`).join("");
})();

// ---- decision log
(() => { const kinds = [...new Set(D.log.map(e=>e.kind))].sort();
  $("#s-log").innerHTML = `<div class="flex" style="margin-top:14px"><select id="lk"><option value="">all kinds</option>${kinds.map(k=>`<option>${esc(k)}</option>`).join("")}</select>
   <select id="la"><option value="">all audiences</option>${auds.map(a=>`<option>${esc(a)}</option>`).join("")}</select><input id="lq" placeholder="search messages" style="flex:1;min-width:180px"><span class="muted" id="ln"></span></div>
   <div class="wrap"><table><thead><tr><th>#</th><th>Kind</th><th>Audience</th><th>Message</th></tr></thead><tbody id="lb"></tbody></table></div>`;
  const draw = () => { const k=$("#lk").value, a=$("#la").value, q=$("#lq").value.toLowerCase();
    const rows = D.log.filter(e=>(!k||e.kind===k)&&(!a||e.audience===a)&&(!q||JSON.stringify(e).toLowerCase().includes(q)));
    $("#ln").textContent = `${rows.length} of ${D.log.length}`;
    $("#lb").innerHTML = rows.map(e=>`<tr><td class="mono">${e.seq}</td><td><span class="pill">${esc(e.kind)}</span></td><td>${esc(e.audience||"")}</td><td>${esc(e.message)}</td></tr>`).join(""); };
  ["lk","la","lq"].forEach(id => $("#"+id).oninput = draw); draw();
})();

let start = "overview"; try { const s = localStorage.getItem("td-tab"); if (s && tabs.some(t=>t[0]===s)) start = s; } catch(e) {}
const fromHash = location.hash.slice(1); if (tabs.some(t=>t[0]===fromHash)) start = fromHash;
show(start);
window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (tabs.some(t=>t[0]===h)) show(h); });
</script></body></html>
"""
