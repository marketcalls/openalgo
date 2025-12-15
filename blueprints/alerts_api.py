
from flask import Blueprint, request, jsonify
from database.alerts_db import Alert, db_session
from utils.logging import get_logger

logger = get_logger(__name__)
alerts_bp = Blueprint('alerts_bp', __name__)

@alerts_bp.route('/add', methods=['POST'])
def add_alert():
    try:
        # Use get_json(silent=True) to return None instead of raising 400/415 if body is bad
        data = request.get_json(silent=True)
        
        # --- FIX 2: Check if JSON exists ---
        if not data:
            return jsonify({"error": "Invalid request. JSON body is missing."}), 400

        # --- FIX 3: Validate Required Fields ---
        required_fields = ['symbol', 'condition', 'price']
        if not all(k in data for k in required_fields):
            return jsonify({"error": f"Missing required fields. Needed: {required_fields}"}), 400

        # --- FIX 4: Validate Condition Values ---
        valid_conditions = ['ABOVE', 'BELOW']
        if data['condition'] not in valid_conditions:
            return jsonify({"error": f"Invalid condition. Must be one of: {valid_conditions}"}), 400

        new_alert = Alert(
            symbol=data['symbol'],
            condition=data['condition'],
            price=data['price']
        )
        db_session.add(new_alert)
        db_session.commit()
        
        logger.info(f"Created new alert for {data['symbol']}")
        return jsonify({"message": "Alert created successfully", "id": new_alert.id}), 201

    except Exception as e:
        # --- FIX 5: Secure Error Handling ---
        # Log the real error for developers
        logger.error(f"Internal Error in /add: {e}") 
        # Send a generic error to the user to hide system details
        return jsonify({"error": "Internal Server Error. Please contact support."}), 500

@alerts_bp.route('/list', methods=['GET'])
def get_alerts():
    try:
        alerts = Alert.query.all()
        return jsonify([a.to_dict() for a in alerts])
    except Exception as e:
        logger.error(f"Error listing alerts: {e}")
        return jsonify({"error": str(e)}), 500
