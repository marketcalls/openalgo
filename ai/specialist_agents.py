"""Specialist AI Agents for institutional trading.

Implements 9 specialized agents: Growth, Value, Momentum, Quant, Macro, 
Sentiment, Sector, Options, and Risk.
"""

import json
from dataclasses import dataclass
from typing import Any

from ai.llm_router import LLMRouter, LLMResponse
from utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class SpecialistResult:
    agent_name: str
    bias: str  # BULLISH, BEARISH, NEUTRAL
    confidence: float  # 0-100
    reason: str
    score: float = 0.0
    details: dict[str, Any] = None

class BaseSpecialist:
    """Base class for all specialist agents."""
    
    def __init__(self, router: LLMRouter = None):
        self.router = router or LLMRouter()
        self.name = "Base"
        self.role = "Generalist"

    def analyze(self, symbol: str, context: dict[str, Any]) -> SpecialistResult:
        """Analyze a symbol based on the specialist's expertise."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(symbol, context)
        
        response = self.router.generate(user_prompt, system=system_prompt)
        if not response.success:
            return SpecialistResult(
                agent_name=self.name,
                bias="NEUTRAL",
                confidence=0.0,
                reason=f"Error: {response.error}"
            )
            
        return self._parse_response(response.text)

    def _build_system_prompt(self) -> str:
        return f"You are an institutional {self.role} agent. Be concise and data-driven."

    def _build_user_prompt(self, symbol: str, context: dict[str, Any]) -> str:
        return f"Analyze {symbol} with the following context: {json.dumps(context)}"

    def _parse_response(self, text: str) -> SpecialistResult:
        """Parse LLM response into a SpecialistResult.
        Expected format: BIAS: [BULLISH/BEARISH/NEUTRAL], CONFIDENCE: [0-100], REASON: [1-sentence]
        """
        bias = "NEUTRAL"
        confidence = 50.0
        reason = "No clear reason provided"
        
        try:
            # Simple line-based parsing
            lines = text.strip().split("\n")
            for line in lines:
                if "BIAS:" in line:
                    bias = line.split("BIAS:")[1].strip().upper()
                elif "CONFIDENCE:" in line:
                    conf_str = line.split("CONFIDENCE:")[1].strip().replace("%", "")
                    confidence = float(conf_str)
                elif "REASON:" in line:
                    reason = line.split("REASON:")[1].strip()
        except Exception as e:
            logger.warning(f"Error parsing specialist response: {e}")
            
        return SpecialistResult(
            agent_name=self.name,
            bias=bias if bias in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL",
            confidence=confidence,
            reason=reason
        )

class GrowthSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Rakesh"
        self.role = "Growth Investor"
        
    def _build_system_prompt(self) -> str:
        return (
            "You are 'Rakesh', a contrarian growth investor inspired by Rakesh Jhunjhunwala. "
            "Focus on high-growth stocks with Revenue CAGR >15%, ROCE >20%, and expanding margins. "
            "Framework: GQM (Growth 40%, Quality 35%, Moat 25%)."
        )

class ValueSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Graham"
        self.role = "Value Investor"

class MomentumSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Jesse"
        self.role = "Momentum Trader"

class QuantSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Simons"
        self.role = "Quant Analyst"

class MacroSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Dalio"
        self.role = "Macro Strategist"

class SentimentSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Buzz"
        self.role = "Sentiment Analyst"

class SectorSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Alpha"
        self.role = "Sector Analyst"

class OptionsSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Greeks"
        self.role = "Options Specialist"

class RiskSpecialist(BaseSpecialist):
    def __init__(self, router: LLMRouter = None):
        super().__init__(router)
        self.name = "Taleb"
        self.role = "Risk Manager"

def get_all_specialists(router: LLMRouter = None) -> list[BaseSpecialist]:
    return [
        GrowthSpecialist(router),
        ValueSpecialist(router),
        MomentumSpecialist(router),
        QuantSpecialist(router),
        MacroSpecialist(router),
        SentimentSpecialist(router),
        SectorSpecialist(router),
        OptionsSpecialist(router),
        RiskSpecialist(router)
    ]
