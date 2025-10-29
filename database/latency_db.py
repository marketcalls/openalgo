from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.pool import NullPool
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Use a separate database for latency logs
LATENCY_DATABASE_URL = os.getenv('LATENCY_DATABASE_URL', 'sqlite:///db/latency.db')

# Conditionally create engine based on DB type
if LATENCY_DATABASE_URL and 'sqlite' in LATENCY_DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    latency_engine = create_engine(
        LATENCY_DATABASE_URL,
        poolclass=NullPool,
        connect_args={'check_same_thread': False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
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
            
            # Get p50, p90, p95, p99 latencies for RTT using numpy for accurate percentile calculation
            import numpy as np
            rtt_latencies = [l[0] for l in OrderLatency.query.with_entities(OrderLatency.rtt_ms).all()]

            p50_rtt = p90_rtt = p95_rtt = p99_rtt = 0
            if rtt_latencies:
                p50_rtt = float(np.percentile(rtt_latencies, 50))
                p90_rtt = float(np.percentile(rtt_latencies, 90))
                p95_rtt = float(np.percentile(rtt_latencies, 95))
                p99_rtt = float(np.percentile(rtt_latencies, 99))
            
            # Calculate SLA compliance (orders under various thresholds)
            orders_under_100ms = OrderLatency.query.filter(OrderLatency.rtt_ms < 100).count()
            orders_under_150ms = OrderLatency.query.filter(OrderLatency.rtt_ms < 150).count()
            orders_under_200ms = OrderLatency.query.filter(OrderLatency.rtt_ms < 200).count()

            sla_100ms = (orders_under_100ms / total_orders * 100) if total_orders else 0
            sla_150ms = (orders_under_150ms / total_orders * 100) if total_orders else 0
            sla_200ms = (orders_under_200ms / total_orders * 100) if total_orders else 0

            # Breakdown by broker
            broker_stats = {}
            brokers = [b[0] for b in OrderLatency.query.with_entities(OrderLatency.broker).distinct().all()]
            for broker in brokers:
                if broker:  # Skip None values
                    broker_orders = OrderLatency.query.filter_by(broker=broker)
                    broker_total = broker_orders.count()
                    broker_rtt_values = [r[0] for r in broker_orders.with_entities(OrderLatency.rtt_ms).all()]

                    # Calculate broker percentiles
                    broker_p50 = broker_p99 = 0
                    if broker_rtt_values:
                        broker_p50 = float(np.percentile(broker_rtt_values, 50))
                        broker_p99 = float(np.percentile(broker_rtt_values, 99))

                    # Calculate broker SLA
                    broker_under_150 = broker_orders.filter(OrderLatency.rtt_ms < 150).count()
                    broker_sla = (broker_under_150 / broker_total * 100) if broker_total else 0

                    broker_stats[broker] = {
                        'total_orders': broker_total,
                        'failed_orders': broker_orders.filter_by(status='FAILED').count(),
                        'avg_rtt': float(broker_orders.with_entities(func.avg(OrderLatency.rtt_ms)).scalar() or 0),
                        'avg_overhead': float(broker_orders.with_entities(func.avg(OrderLatency.overhead_ms)).scalar() or 0),
                        'avg_total': float(broker_orders.with_entities(func.avg(OrderLatency.total_latency_ms)).scalar() or 0),
                        'p50_rtt': broker_p50,
                        'p99_rtt': broker_p99,
                        'sla_150ms': broker_sla
                    }

            return {
                'total_orders': total_orders,
                'failed_orders': failed_orders,
                'success_rate': ((total_orders - failed_orders) / total_orders * 100) if total_orders else 0,
                'avg_rtt': float(avg_rtt),
                'avg_overhead': float(avg_overhead),
                'avg_total': float(avg_total),
                'p50_rtt': float(p50_rtt),
                'p90_rtt': float(p90_rtt),
                'p95_rtt': float(p95_rtt),
                'p99_rtt': float(p99_rtt),
                'sla_100ms': float(sla_100ms),
                'sla_150ms': float(sla_150ms),
                'sla_200ms': float(sla_200ms),
                'broker_stats': broker_stats
            }
        except Exception as e:
            logger.error(f"Error getting latency stats: {str(e)}")
            return {
                'total_orders': 0,
                'failed_orders': 0,
                'success_rate': 0,
                'avg_rtt': 0,
                'avg_overhead': 0,
                'avg_total': 0,
                'p50_rtt': 0,
                'p90_rtt': 0,
                'p95_rtt': 0,
                'p99_rtt': 0,
                'sla_100ms': 0,
                'sla_150ms': 0,
                'sla_200ms': 0,
                'broker_stats': {}
            }

def init_latency_db():
    """Initialize the latency database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = LATENCY_DATABASE_URL.replace('sqlite:///', '')
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(LatencyBase, latency_engine, "Latency DB", logger)
