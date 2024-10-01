from flask_restx import Api
from flask import Blueprint

api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')
api = Api(api_v1_bp, version='1.0', title='OpenAlgo API', description='API for OpenAlgo Trading Platform')

# Import namespaces
from .place_order import api as place_order_ns
from .place_smart_order import api as place_smart_order_ns
from .modify_order import api as modify_order_ns
from .cancel_order import api as cancel_order_ns
from .close_position import api as close_position_ns
from .cancel_all_order import api as cancel_all_order_ns

# Add namespaces
api.add_namespace(place_order_ns, path='/placeorder')
api.add_namespace(place_smart_order_ns, path='/placesmartorder')
api.add_namespace(modify_order_ns, path='/modifyorder')
api.add_namespace(cancel_order_ns, path='/cancelorder')
api.add_namespace(close_position_ns, path='/closeposition')
api.add_namespace(cancel_all_order_ns, path='/cancelallorder')
