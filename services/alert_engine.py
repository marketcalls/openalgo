
from database.alerts_db import Alert, db_session
from services.telegram_alert_service import telegram_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)

class AlertEngine:
    
    @staticmethod
    def check_market(market_data):
        """
        market_data is a dictionary: {'INFY': 1505.00, 'RELIANCE': 2400.00}
        """
        # 1. Get all active alerts
        try:
            active_alerts = Alert.query.filter_by(status="ACTIVE").all()
        except Exception as e:
            logger.error(f"Failed to fetch active alerts: {e}")
            return

        for alert in active_alerts:
            # --- FIX 6: Isolate Errors per Alert ---
            try:
                # 2. Get current price for this symbol
                current_price = market_data.get(alert.symbol)

                if current_price is None:
                    continue # Skip if we don't have data for this symbol

                # 3. Check Condition
                triggered = False
                
                # A. Simple State Checks (Triggers immediately if condition is met)
                if alert.condition == "ABOVE" and current_price > alert.price:
                    triggered = True
                elif alert.condition == "BELOW" and current_price < alert.price:
                    triggered = True
                    
                # B. Smart "CROSS" Check (Requires History)
                elif alert.condition == 'CROSS' and alert.last_price is not None:
                    
                    # Logic: Did the price line pass through the target?
                    
                    # Case A: Crossed Up (Prev < Target <= Curr)
                    crossed_up = (alert.last_price < alert.price) and (current_price >= alert.price)
                    
                    # Case B: Crossed Down (Prev > Target >= Curr)
                    crossed_down = (alert.last_price > alert.price) and (current_price <= alert.price)
                    
                    if crossed_up or crossed_down:
                        triggered = True

                # 4. Fire Alert
                if triggered:
                    message = f"🚀 **ALERT TRIGGERED**\n\nSymbol: `{alert.symbol}`\nCondition: `{alert.condition}`\nPrice: `{current_price}`"
                    logger.info(message)
                    telegram_alert_service.send_broadcast_alert(message)
                    alert.status = "TRIGGERED"
                
                # CRITICAL: Save the current price as 'last_price' for the next run
                # This ensures we have memory for the next check
                alert.last_price = current_price
                db_session.commit()
                    
            except Exception as e:
                # If THIS alert fails, log it and rollback ONLY this session state
                logger.error(f"Failed to process alert {alert.id}: {e}")
                db_session.rollback()
                # 'continue' happens automatically here, moving to the next alert
