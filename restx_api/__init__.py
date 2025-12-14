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
from .multiquotes import api as multiquotes_ns
from .history import api as history_ns
from .depth import api as depth_ns
from .option_chain import api as option_chain_ns
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
from .search import api as search_ns
from .expiry import api as expiry_ns
from .option_symbol import api as option_symbol_ns
from .options_order import api as options_order_ns
from .options_multiorder import api as options_multiorder_ns
from .option_greeks import api as option_greeks_ns
from .synthetic_future import api as synthetic_future_ns
from .analyzer import api as analyzer_ns
from .ping import api as ping_ns
from .telegram_bot import api as telegram_ns
from .margin import api as margin_ns
from .instruments import api as instruments_ns
from .chart_api import api as chart_ns

# Add namespaces
api.add_namespace(place_order_ns, path='/placeorder')
api.add_namespace(place_smart_order_ns, path='/placesmartorder')
api.add_namespace(modify_order_ns, path='/modifyorder')
api.add_namespace(cancel_order_ns, path='/cancelorder')
api.add_namespace(close_position_ns, path='/closeposition')
api.add_namespace(cancel_all_order_ns, path='/cancelallorder')
api.add_namespace(quotes_ns, path='/quotes')
api.add_namespace(multiquotes_ns, path='/multiquotes')
api.add_namespace(history_ns, path='/history')
api.add_namespace(depth_ns, path='/depth')
api.add_namespace(option_chain_ns, path='/optionchain')
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
api.add_namespace(search_ns, path='/search')
api.add_namespace(expiry_ns, path='/expiry')
api.add_namespace(option_symbol_ns, path='/optionsymbol')
api.add_namespace(options_order_ns, path='/optionsorder')
api.add_namespace(options_multiorder_ns, path='/optionsmultiorder')
api.add_namespace(option_greeks_ns, path='/optiongreeks')
api.add_namespace(synthetic_future_ns, path='/syntheticfuture')
api.add_namespace(analyzer_ns, path='/analyzer')
api.add_namespace(ping_ns, path='/ping')
api.add_namespace(telegram_ns, path='/telegram')
api.add_namespace(margin_ns, path='/margin')
api.add_namespace(instruments_ns, path='/instruments')
api.add_namespace(chart_ns, path='/chart')
