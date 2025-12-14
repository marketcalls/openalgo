
from flask import Blueprint, request, jsonify
from database.alerts_db import Alert, db_session
from utils.logging import get_logger

logger = get_logger(__name__)
alerts_bp = Blueprint('alerts_bp', __name__)

@alerts_bp.route('/add', methods=['POST'])
def add_alert():
    try:
        data = request.json
        # data expects: {"symbol": "INFY", "condition": "ABOVE", "price": 1500}
        
        if not all(k in data for k in ('symbol', 'condition', 'price')):
            return jsonify({"error": "Missing required fields: symbol, condition, price"}), 400
            
        new_alert = Alert(
            symbol=data['symbol'],
            condition=data['condition'],
            price=data['price']
        )
        db_session.add(new_alert)
        db_session.commit()
        
        logger.info(f"Created new alert for {data['symbol']}")
        return jsonify({"message": "Alert Created", "id": new_alert.id}), 201
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        db_session.rollback()
        return jsonify({"error": str(e)}), 500

@alerts_bp.route('/list', methods=['GET'])
def get_alerts():
    try:
        alerts = Alert.query.all()
        return jsonify([a.to_dict() for a in alerts])
    except Exception as e:
        logger.error(f"Error listing alerts: {e}")
        return jsonify({"error": str(e)}), 500
