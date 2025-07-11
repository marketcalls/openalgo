from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Use a separate database for latency logs
LATENCY_DATABASE_URL = os.getenv('LATENCY_DATABASE_URL', 'sqlite:///db/latency.db')

latency_engine = create_engine(
    LATENCY_DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

latency_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=latency_engine))
LatencyBase = declarative_base()
LatencyBase.query = latency_session.query_property()

class OrderLatency(LatencyBase):
    """Model for tracking end-to-end order execution latency"""
    __tablename__ = 'order_latency'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    order_id = Column(String(100), nullable=False)
    user_id = Column(Integer)
    broker = Column(String(50))
    symbol = Column(String(50))
    order_type = Column(String(20))  # MARKET, LIMIT, etc.
    
    # Round-trip time (comparable to Postman/Bruno)
    rtt_ms = Column(Float)
    
    # Our processing overhead
    validation_latency_ms = Column(Float)  # Pre-request processing
    response_latency_ms = Column(Float)  # Post-response processing
    overhead_ms = Column(Float)  # Total overhead
    
    # Total time including overhead
    total_latency_ms = Column(Float, nullable=False)
    
    # Request details
    request_body = Column(JSON)  # Original request
    response_body = Column(JSON)  # Broker response
    status = Column(String(20))  # SUCCESS, FAILED, PARTIAL
    error = Column(String(500))  # Error message if any
    
    @staticmethod
    def log_latency(order_id, user_id, broker, symbol, order_type, latencies, request_body, response_body, status, error=None):
        """Log order execution latency"""
        try:
            log = OrderLatency(
                order_id=order_id,
                user_id=user_id,
                broker=broker,
                symbol=symbol,
                order_type=order_type,
                rtt_ms=latencies.get('rtt', 0),
                validation_latency_ms=latencies.get('validation', 0),
                response_latency_ms=latencies.get('broker_response', 0),
                overhead_ms=latencies.get('overhead', 0),
                total_latency_ms=latencies.get('total', 0),
                request_body=request_body,
                response_body=response_body,
                status=status,
                error=error
            )
            latency_session.add(log)
            latency_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error logging latency: {str(e)}")
            latency_session.rollback()
            return False

    @staticmethod
    def get_recent_logs(limit=100):
        """Get recent latency logs ordered by timestamp"""
        try:
            return OrderLatency.query.order_by(OrderLatency.timestamp.desc()).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting recent latency logs: {str(e)}")
            return []

    @staticmethod
    def get_latency_stats():
        """Get latency statistics"""
        try:
            from sqlalchemy import func
            
            # Overall stats
            total_orders = OrderLatency.query.count()
            failed_orders = OrderLatency.query.filter(OrderLatency.status == 'FAILED').count()
            
            # Get average latencies
            avg_rtt = latency_session.query(func.avg(OrderLatency.rtt_ms)).scalar() or 0
            avg_overhead = latency_session.query(func.avg(OrderLatency.overhead_ms)).scalar() or 0
            avg_total = latency_session.query(func.avg(OrderLatency.total_latency_ms)).scalar() or 0
            
            # Get p50, p90, p99 latencies for RTT
            rtt_latencies = [l[0] for l in OrderLatency.query.with_entities(OrderLatency.rtt_ms).all()]
            rtt_latencies.sort()
            
            p50_rtt = p90_rtt = p99_rtt = 0
            if rtt_latencies:
                p50_rtt = rtt_latencies[int(len(rtt_latencies) * 0.5)]
                p90_rtt = rtt_latencies[int(len(rtt_latencies) * 0.9)]
                p99_rtt = rtt_latencies[int(len(rtt_latencies) * 0.99)]
            
            # Breakdown by broker
            broker_stats = {}
            brokers = [b[0] for b in OrderLatency.query.with_entities(OrderLatency.broker).distinct().all()]
            for broker in brokers:
                if broker:  # Skip None values
                    broker_orders = OrderLatency.query.filter_by(broker=broker)
                    broker_stats[broker] = {
                        'total_orders': broker_orders.count(),
                        'failed_orders': broker_orders.filter_by(status='FAILED').count(),
                        'avg_rtt': float(broker_orders.with_entities(func.avg(OrderLatency.rtt_ms)).scalar() or 0),
                        'avg_overhead': float(broker_orders.with_entities(func.avg(OrderLatency.overhead_ms)).scalar() or 0),
                        'avg_total': float(broker_orders.with_entities(func.avg(OrderLatency.total_latency_ms)).scalar() or 0)
                    }
            
            return {
                'total_orders': total_orders,
                'failed_orders': failed_orders,
                'avg_rtt': float(avg_rtt),
                'avg_overhead': float(avg_overhead),
                'avg_total': float(avg_total),
                'p50_rtt': float(p50_rtt),
                'p90_rtt': float(p90_rtt),
                'p99_rtt': float(p99_rtt),
                'broker_stats': broker_stats
            }
        except Exception as e:
            logger.error(f"Error getting latency stats: {str(e)}")
            return {
                'total_orders': 0,
                'failed_orders': 0,
                'avg_rtt': 0,
                'avg_overhead': 0,
                'avg_total': 0,
                'p50_rtt': 0,
                'p90_rtt': 0,
                'p99_rtt': 0,
                'broker_stats': {}
            }

def init_latency_db():
    """Initialize the latency database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = LATENCY_DATABASE_URL.replace('sqlite:///', '')
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    logger.info(f"Initializing Latency DB at: {LATENCY_DATABASE_URL}")
    LatencyBase.metadata.create_all(bind=latency_engine)
