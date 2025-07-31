import time
from functools import wraps
from flask import g, request
from database.latency_db import OrderLatency, latency_session, init_latency_db
from database.auth_db import get_broker_name
from utils.logging import get_logger
from flask_restx import Resource

logger = get_logger(__name__)

class LatencyTracker:
    """Helper class to track latencies across different stages of order execution"""
    
    def __init__(self):
        self.start_time = time.time()
        self.stage_times = {}
        self.current_stage = None
        self.stage_start = None
        self.request_start = None
        self.request_end = None
    
    def start_stage(self, stage_name):
        """Start timing a new stage"""
        self.current_stage = stage_name
        self.stage_start = time.time()
        if stage_name == 'broker_request':
            self.request_start = self.stage_start
    
    def end_stage(self):
        """End timing the current stage"""
        if self.current_stage and self.stage_start:
            current_time = time.time()
            duration = (current_time - self.stage_start) * 1000  # Convert to milliseconds
            self.stage_times[self.current_stage] = duration
            if self.current_stage == 'broker_request':
                self.request_end = current_time
            self.current_stage = None
            self.stage_start = None
    
    def get_total_time(self):
        """Get total time since tracker was created"""
        return (time.time() - self.start_time) * 1000  # Convert to milliseconds
    
    def get_rtt(self):
        """Get round-trip time (comparable to Postman/Bruno)"""
        if self.request_start and self.request_end:
            return (self.request_end - self.request_start) * 1000
        return 0
    
    def get_overhead(self):
        """Get total overhead from our processing"""
        return (self.stage_times.get('validation', 0) + 
                self.stage_times.get('broker_response', 0))

def track_latency(api_type):
    """Decorator to track latency for API endpoints"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Initialize latency tracker
            tracker = LatencyTracker()
            g.latency_tracker = tracker
            
            try:
                # Start validation stage
                tracker.start_stage('validation')
                
                # Get request data for logging
                request_data = request.get_json() if request.is_json else {}
                
                # End validation stage after getting request data
                tracker.end_stage()
                
                # Start broker request stage
                tracker.start_stage('broker_request')
                
                # Execute the actual endpoint
                response = f(*args, **kwargs)
                
                # End broker request stage
                tracker.end_stage()
                
                # Start response processing stage
                tracker.start_stage('broker_response')
                
                # Get response data
                if hasattr(response, 'json'):
                    response_data = response.json
                elif isinstance(response, tuple) and len(response) > 0:
                    response_data = response[0]
                else:
                    response_data = {}
                
                # End response processing stage
                tracker.end_stage()
                
                # Get status code
                if isinstance(response, tuple):
                    status_code = response[1] if len(response) > 1 else 200
                else:
                    status_code = getattr(response, 'status_code', 200)
                
                # Calculate latencies
                rtt = tracker.get_rtt()
                overhead = tracker.get_overhead()
                total = rtt + overhead
                
                # Log the latency data
                # Handle the case where orderid might be null in the response
                order_id = response_data.get('orderid')
                if order_id is None:
                    order_id = response_data.get('request_id', 'unknown')
                
                # Get broker name from auth_db using API key
                broker_name = None
                if 'apikey' in request_data:
                    broker_name = get_broker_name(request_data['apikey'])
                
                OrderLatency.log_latency(
                    order_id=order_id,
                    user_id=g.get('user_id'),
                    broker=broker_name,
                    symbol=request_data.get('symbol'),
                    order_type=api_type,
                    latencies={
                        'rtt': rtt,  # Round-trip time (comparable to Postman/Bruno)
                        'validation': tracker.stage_times.get('validation', 0),
                        'broker_response': tracker.stage_times.get('broker_response', 0),
                        'overhead': overhead,
                        'total': total
                    },
                    request_body=request_data,
                    response_body=response_data,
                    status='SUCCESS' if status_code < 400 else 'FAILED',
                    error=response_data.get('message') if status_code >= 400 else None
                )
                
                return response
                
            except Exception as e:
                # Log error latency
                total_time = tracker.get_total_time()
                rtt = tracker.get_rtt()
                overhead = tracker.get_overhead()
                
                # Get broker name from auth_db using API key if available
                broker_name = None
                if 'request_data' in locals() and 'apikey' in request_data:
                    broker_name = get_broker_name(request_data['apikey'])
                
                OrderLatency.log_latency(
                    order_id='error',
                    user_id=g.get('user_id'),
                    broker=broker_name,
                    symbol=request_data.get('symbol') if 'request_data' in locals() else None,
                    order_type=api_type,
                    latencies={
                        'rtt': rtt,
                        'validation': tracker.stage_times.get('validation', 0),
                        'broker_response': 0,
                        'overhead': overhead,
                        'total': total_time
                    },
                    request_body=request_data if 'request_data' in locals() else None,
                    response_body=None,
                    status='FAILED',
                    error=str(e)
                )
                raise
                
            finally:
                latency_session.remove()
                
        return wrapped
    return decorator

def wrap_resource_methods(resource_class, api_type):
    """Helper function to wrap all methods of a Resource class with latency tracking"""
    for method in ['get', 'post', 'put', 'delete', 'patch']:
        if hasattr(resource_class, method):
            original_method = getattr(resource_class, method)
            if isinstance(original_method, (classmethod, staticmethod)):
                original_method = original_method.__get__(None, resource_class)
            setattr(resource_class, method, track_latency(api_type)(original_method))

def init_latency_monitoring(app):
    """Initialize latency monitoring"""
    # Initialize the latency database
    init_latency_db()
    
    # Import all RESTX API resources
    from restx_api import api
    
    # Map of endpoint names to their types
    api_types = {
        'place_order': 'PLACE',
        'place_smart_order': 'SMART',
        'modify_order': 'MODIFY',
        'cancel_order': 'CANCEL',
        'close_position': 'CLOSE',
        'cancel_all_order': 'CANCEL_ALL',
        'quotes': 'QUOTES',
        'history': 'HISTORY',
        'depth': 'DEPTH',
        'intervals': 'INTERVALS',
        'funds': 'FUNDS',
        'orderbook': 'ORDERBOOK',
        'tradebook': 'TRADEBOOK',
        'positionbook': 'POSITIONBOOK',
        'holdings': 'HOLDINGS',
        'basket_order': 'BASKET',
        'split_order': 'SPLIT',
        'orderstatus': 'STATUS',
        'openposition': 'POSITION'
    }
    
    # Wrap all API endpoints with latency tracking
    for namespace in api.namespaces:
        api_type = api_types.get(namespace.name, namespace.name.upper())
        
        # Get all resources in the namespace
        for resource in namespace.resources:
            # Get the actual resource class
            resource_class = resource.resource
            
            # Wrap all methods of the resource
            wrap_resource_methods(resource_class, api_type)
