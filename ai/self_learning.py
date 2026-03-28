"""Self-Learning Engine (Option 2) for AI Agents.

Tracks agent predictions, verifies outcomes against actual market data,
and adjusts agent weights dynamically based on performance.
"""

import json
from datetime import datetime, timezone
from typing import Any

from database.ai_db import AiSession, AiDecision, get_pending_decisions, update_outcome
from database.settings_db import get_agent_weights, set_agent_weights
from services.market_data_service import get_ltp_value
from utils.logging import get_logger

logger = get_logger(__name__)

class SelfLearningEngine:
    """Orchestrates the self-learning loop."""
    
    def __init__(self, price_service=None):
        # Use provided price service or default to the global market data service
        self.get_ltp = price_service.get_ltp_value if price_service else get_ltp_value
        self.verifier = OutcomeVerifier(self.get_ltp)
        self.adjuster = WeightAdjuster()

    def run_learning_cycle(self):
        """Run one cycle of outcome verification and weight adjustment."""
        logger.info("Starting self-learning cycle...")
        
        # 1. Get pending decisions
        pending = get_pending_decisions(limit=100)
        if not pending:
            logger.info("No pending AI decisions to verify.")
        else:
            # 2. Verify outcomes
            verified_count = 0
            for decision in pending:
                outcome_data = self.verifier.verify(decision)
                if outcome_data:
                    update_outcome(decision.id, outcome_data)
                    verified_count += 1
            
            logger.info(f"Verified {verified_count} AI decisions.")

        # 3. Always check if weights need re-balancing based on historical Correct/Incorrect
        # even if 0 were verified just now, we might have new verified data from previous runs
        self.adjuster.adjust_weights()

class OutcomeVerifier:
    """Verifies AI predictions against actual market prices."""
    
    def __init__(self, get_ltp_func):
        self.get_ltp = get_ltp_func

    def verify(self, decision: Any) -> dict[str, Any] | None:
        """Verify a single decision. Returns outcome data if verified."""
        try:
            current_price = self.get_ltp(decision.symbol, decision.exchange)
            if not current_price or current_price == 0:
                return None

            # Logic to determine outcome
            predicted_price = decision.predicted_price or 0.0
            if predicted_price == 0:
                return None

            actual_price = current_price
            price_change_pct = (actual_price - predicted_price) / predicted_price if predicted_price > 0 else 0
            
            # Simple threshold: 0.5% move in predicted direction = CORRECT
            actual_direction = "FLAT"
            if price_change_pct > 0.005: # 0.5% threshold
                actual_direction = "UP"
            elif price_change_pct < -0.005:
                actual_direction = "DOWN"

            # Match signal to actual direction
            signal = decision.signal.upper()
            is_correct = False
            if signal in ("BUY", "STRONG_BUY") and actual_direction == "UP":
                is_correct = True
            elif signal in ("SELL", "STRONG_SELL") and actual_direction == "DOWN":
                is_correct = True
            elif signal == "HOLD" and actual_direction == "FLAT":
                is_correct = True

            return {
                "actual_price": actual_price,
                "outcome": "CORRECT" if is_correct else "INCORRECT",
                "accuracy_score": 1.0 if is_correct else 0.0,
                "actual_direction": actual_direction
            }
        except Exception as e:
            logger.warning(f"Error verifying decision {decision.id}: {e}")
            return None

class WeightAdjuster:
    """Adjusts agent weights based on historical accuracy stored in AI DB."""

    def adjust_weights(self):
        """Update agent weights based on recent performance (Last 100 verified trades)."""
        session = AiSession()
        try:
            # Fetch last 100 resolved decisions
            resolved = session.query(AiDecision).filter(AiDecision.outcome != "PENDING").order_by(AiDecision.resolved_at.desc()).limit(100).all()
            if not resolved:
                return

            current_weights = get_agent_weights()
            agent_performance = {name: {"correct": 0, "total": 0} for name in current_weights.keys()}

            # Analyze which agents were right in each winning/losing trade
            for dec in resolved:
                if not dec.sub_scores_json:
                    continue
                
                try:
                    scores = json.loads(dec.sub_scores_json)
                    agents = scores.get("agent_breakdown", {})
                    
                    for agent_name, agent_data in agents.items():
                        if agent_name not in agent_performance:
                            continue
                        
                        agent_performance[agent_name]["total"] += 1
                        # If the agent's bias matched the trade's final outcome
                        # dec.outcome is for the COMPOSITE signal. 
                        # We check if this specific agent was right.
                        agent_bias = agent_data.get("bias", "NEUTRAL")
                        actual_dir = dec.actual_direction # UP, DOWN, FLAT
                        
                        agent_is_correct = False
                        if agent_bias == "BULLISH" and actual_dir == "UP":
                            agent_is_correct = True
                        elif agent_bias == "BEARISH" and actual_dir == "DOWN":
                            agent_is_correct = True
                        elif agent_bias == "NEUTRAL" and actual_dir == "FLAT":
                            agent_is_correct = True
                            
                        if agent_is_correct:
                            agent_performance[agent_name]["correct"] += 1
                except Exception:
                    continue

            # Calculate new weights
            new_weights = {}
            for name, perf in agent_performance.items():
                if perf["total"] < 5: # Need at least 5 samples to adjust
                    new_weights[name] = current_weights.get(name, 1.0)
                    continue
                
                accuracy = perf["correct"] / perf["total"]
                # Dynamic weight adjustment: 
                # Accuracy 0.5 (random) -> Weight 1.0
                # Accuracy 0.8 -> Weight 1.6
                # Accuracy 0.2 -> Weight 0.4
                # Capped between 0.5 and 2.0 to prevent total deactivation
                calculated_weight = round(max(0.5, min(2.0, accuracy * 2)), 2)
                new_weights[name] = calculated_weight
                
                if calculated_weight != current_weights.get(name):
                    logger.info(f"Self-Learning: Adjusted {name} weight: {current_weights.get(name)} -> {calculated_weight} (Acc: {accuracy:.2f})")

            if new_weights:
                set_agent_weights(new_weights)

        except Exception as e:
            logger.error(f"Error adjusting agent weights: {e}")
        finally:
            AiSession.remove()
