"""Deterministic text checks shared by story analysis and verification.

Everything here is lexicon/regex based on purpose: these checks must be able to
reject a creative draft without asking a model for its opinion.
"""
import re


def has_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text or "", re.IGNORECASE) is not None


def find_terms(text: str, terms) -> list[str]:
    return [t for t in terms if has_term(text, t)]


def description_tags(scene, sensitive_terms: dict) -> set[str]:
    """Rating tags implied by either description (conservative union)."""
    text = f"{scene.human_description} {scene.ai_description}"
    return {tag for term, tag in sensitive_terms.items() if has_term(text, term)}


def description_mismatches(scene, sensitive_terms: dict) -> list[dict]:
    """Sensitive terms that appear in only one of the human / AI descriptions."""
    out = []
    for term, tag in sensitive_terms.items():
        in_h, in_a = has_term(scene.human_description, term), has_term(scene.ai_description, term)
        if in_h != in_a:
            out.append({"scene_id": scene.scene_id, "term": term, "implied_tag": tag,
                        "in_human_description": in_h, "in_ai_description": in_a})
    return out


def injection_hits(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, text or "", re.IGNORECASE)]


def vocative_kinship_terms(text: str, lexicon: dict) -> list[str]:
    """Kinship terms used to *address* someone ("Beti, ...", "..., Dadi.", "..., Amar Mama!").

    A term merely mentioned mid-sentence ("send Dadi away") is not a form of
    address and says nothing about the speaker/addressee relationship.
    """
    found = []
    for term in lexicon:
        pat = rf"(?:^|[,.!?]\s+)(?:[A-Z]\w+\s+)?{re.escape(term)}\s*[,.!?]"
        if re.search(pat, text or "", re.IGNORECASE):
            found.append(term)
    return found
