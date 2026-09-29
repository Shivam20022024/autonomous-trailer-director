"""Budget tracking for model calls, media analysis and total estimated cost."""


class Budget:
    def __init__(self, limits: dict, cost_sheet: dict):
        self.max_calls = limits["max_model_calls"]
        self.max_media_minutes = limits["max_media_minutes"]
        self.max_usd = limits["max_total_usd"]
        self.cost_sheet = cost_sheet
        self.calls = 0
        self.media_minutes = 0.0
        self.usd = 0.0
        self.ledger: list[dict] = []

    def model_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price = self.cost_sheet["models"].get(model, {"input_per_mtok": 0.0, "output_per_mtok": 0.0})
        return (input_tokens * price["input_per_mtok"] + output_tokens * price["output_per_mtok"]) / 1_000_000

    def media_cost(self, minutes: float) -> float:
        return minutes * self.cost_sheet["media"]["keyframe_check_per_clip_minute"]

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // self.cost_sheet.get("chars_per_token_estimate", 4))

    def can_call(self, usd: float) -> tuple[bool, str]:
        if self.calls + 1 > self.max_calls:
            return False, f"model-call limit reached ({self.max_calls})"
        if self.usd + usd > self.max_usd:
            return False, f"cost limit would be exceeded (${self.usd + usd:.4f} > ${self.max_usd:.2f})"
        return True, ""

    def can_analyse_media(self, minutes: float) -> tuple[bool, str]:
        if self.media_minutes + minutes > self.max_media_minutes:
            return False, f"media-analysis limit would be exceeded ({self.media_minutes + minutes:.2f} > {self.max_media_minutes} min)"
        if self.usd + self.media_cost(minutes) > self.max_usd:
            return False, "cost limit would be exceeded by media analysis"
        return True, ""

    def charge_call(self, task: str, model: str, input_tokens: int, output_tokens: int, audience=None) -> float:
        usd = self.model_cost(model, input_tokens, output_tokens)
        self.calls += 1
        self.usd += usd
        self.ledger.append({"type": "model_call", "task": task, "model": model, "audience": audience,
                            "input_tokens": input_tokens, "output_tokens": output_tokens, "usd": round(usd, 6)})
        return usd

    def charge_media(self, task: str, minutes: float, audience=None) -> float:
        usd = self.media_cost(minutes)
        self.media_minutes += minutes
        self.usd += usd
        self.ledger.append({"type": "media_analysis", "task": task, "audience": audience,
                            "minutes": round(minutes, 3), "usd": round(usd, 6)})
        return usd

    def spent_for(self, audience) -> float:
        return round(sum(e["usd"] for e in self.ledger if e.get("audience") == audience), 6)

    def summary(self) -> dict:
        return {"model_calls": self.calls, "max_model_calls": self.max_calls,
                "media_minutes": round(self.media_minutes, 3), "max_media_minutes": self.max_media_minutes,
                "estimated_usd": round(self.usd, 6), "max_total_usd": self.max_usd,
                "within_budget": self.calls <= self.max_calls and self.usd <= self.max_usd
                and self.media_minutes <= self.max_media_minutes,
                "ledger": self.ledger}
