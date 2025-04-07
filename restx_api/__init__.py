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
from .quotes import api as quotes_ns
from .history import api as history_ns
from .depth import api as depth_ns
from .intervals import api as intervals_ns
from .funds import api as funds_ns
from .orderbook import api as orderbook_ns
from .tradebook import api as tradebook_ns
from .positionbook import api as positionbook_ns
from .holdings import api as holdings_ns
from .basket_order import api as basket_order_ns
from .split_order import api as split_order_ns
from .orderstatus import api as orderstatus_ns
from .openposition import api as openposition_ns
from .ticker import api as ticker_ns
from .symbol import api as symbol_ns

# Add namespaces
api.add_namespace(place_order_ns, path='/placeorder')
api.add_namespace(place_smart_order_ns, path='/placesmartorder')
api.add_namespace(modify_order_ns, path='/modifyorder')
api.add_namespace(cancel_order_ns, path='/cancelorder')
api.add_namespace(close_position_ns, path='/closeposition')
api.add_namespace(cancel_all_order_ns, path='/cancelallorder')
api.add_namespace(quotes_ns, path='/quotes')
api.add_namespace(history_ns, path='/history')
api.add_namespace(depth_ns, path='/depth')
api.add_namespace(intervals_ns, path='/intervals')
api.add_namespace(funds_ns, path='/funds')
api.add_namespace(orderbook_ns, path='/orderbook')
api.add_namespace(tradebook_ns, path='/tradebook')
api.add_namespace(positionbook_ns, path='/positionbook')
api.add_namespace(holdings_ns, path='/holdings')
api.add_namespace(basket_order_ns, path='/basketorder')
api.add_namespace(split_order_ns, path='/splitorder')
api.add_namespace(orderstatus_ns, path='/orderstatus')
api.add_namespace(openposition_ns, path='/openposition')
api.add_namespace(ticker_ns, path='/ticker')
api.add_namespace(symbol_ns, path='/symbol')
