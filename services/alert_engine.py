
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
        try:
            # 1. Get all active alerts
            active_alerts = Alert.query.filter_by(status="ACTIVE").all()

            for alert in active_alerts:
                # 2. Get current price for this symbol
                current_price = market_data.get(alert.symbol)

                if current_price is None:
                    continue # Skip if we don't have data for this symbol

                # 3. Check Condition
                triggered = False
                if alert.condition == "ABOVE" and current_price > alert.price:
                    triggered = True
                elif alert.condition == "BELOW" and current_price < alert.price:
                    triggered = True

                # 4. Fire Alert
                if triggered:
                    message = f"🚨 ALERT: {alert.symbol} is {alert.condition} {alert.price}. Current: {current_price}"
                    logger.info(message)
                    
                    # Use broadcast method to send to all enabled users
                    telegram_alert_service.send_broadcast_alert(message)
                    
                    # 5. Mark as Triggered
                    alert.status = "TRIGGERED"
                    db_session.commit()
                    
        except Exception as e:
            logger.error(f"Error in AlertEngine.check_market: {e}")
            db_session.rollback()
