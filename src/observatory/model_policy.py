from dataclasses import dataclass
from typing import Literal

ModelTier = Literal["fast", "strong"]
AnalystUseCase = Literal["current_data", "web", "temporal", "rugcheck"]

USE_CASE_TIERS: dict[AnalystUseCase, ModelTier] = {
    "current_data": "fast",
    "web": "strong",
    "temporal": "strong",
    "rugcheck": "strong",
}


@dataclass(frozen=True)
class ModelPolicy:
    fast_model: str
    strong_model: str

    def __post_init__(self) -> None:
        if not self.fast_model.strip():
            raise ValueError("fast_model must not be empty")
        if not self.strong_model.strip():
            raise ValueError("strong_model must not be empty")

    def tier_for(self, use_case: AnalystUseCase) -> ModelTier:
        try:
            return USE_CASE_TIERS[use_case]
        except KeyError as error:
            raise ValueError(f"unsupported analyst use case: {use_case}") from error

    def model_for(self, use_case: AnalystUseCase) -> str:
        if self.tier_for(use_case) == "fast":
            return self.fast_model
        return self.strong_model
