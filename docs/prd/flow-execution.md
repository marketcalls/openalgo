# Flow Execution Engine

This document describes the backend execution engine that runs Flow workflows.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Workflow Execution                              │
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐ │
│  │   Trigger       │    │  Execution      │    │  Result         │ │
│  │   Sources       │───▶│  Engine         │───▶│  Storage        │ │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘ │
│         │                       │                      │            │
│  ┌──────┴──────┐        ┌──────┴──────┐        ┌──────┴──────┐    │
│  │ APScheduler │        │ Node        │        │ Database    │    │
│  │ Webhook     │        │ Executor    │        │ (SQLite)    │    │
│  │ Manual      │        │             │        │             │    │
│  └─────────────┘        └──────┬──────┘        └─────────────┘    │
│                                │                                    │
│                        ┌───────┴───────┐                           │
│                        │               │                           │
│                 ┌──────▼──────┐ ┌─────▼──────┐                    │
│                 │ Workflow    │ │ OpenAlgo   │                    │
│                 │ Context     │ │ Client     │                    │
│                 └─────────────┘ └────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Components

### File Structure

```
services/
├── flow_executor_service.py    # Main execution engine (~1700 lines)
├── flow_openalgo_client.py     # OpenAlgo API wrapper (~500 lines)
└── flow_scheduler.py           # APScheduler integration
```

### Core Classes

| Class | Purpose |
|-------|---------|
| `WorkflowContext` | Maintains execution state and variables |
| `NodeExecutor` | Executes individual node operations |
| `FlowOpenAlgoClient` | Wraps OpenAlgo internal APIs |

## WorkflowContext

Manages state during workflow execution.

```python
class WorkflowContext:
    def __init__(self, webhook_data: dict = None):
        self.variables: Dict[str, Any] = {}
        self.condition_results: Dict[str, bool] = {}
        self.webhook_data = webhook_data or {}

    def set_variable(self, name: str, value: Any):
        """Store a variable for later use"""
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Retrieve a stored variable"""
        return self.variables.get(name, default)

    def set_condition_result(self, node_id: str, result: bool):
        """Store condition result for edge routing"""
        self.condition_results[node_id] = result

    def get_condition_result(self, node_id: str) -> bool:
        """Get condition result for edge routing"""
        return self.condition_results.get(node_id, False)

    def interpolate(self, text: str) -> str:
        """Replace {{variable}} placeholders with values"""
        if not isinstance(text, str):
            return text

        # Built-in variables
        now = datetime.now()
        built_ins = {
            'timestamp': now.isoformat(),
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%H:%M:%S'),
            'hour': str(now.hour),
            'minute': str(now.minute),
            'second': str(now.second),
            'weekday': now.strftime('%A'),
        }

        # Replace built-ins
        for key, value in built_ins.items():
            text = text.replace(f'{{{{{key}}}}}', value)

        # Replace user variables
        for key, value in self.variables.items():
            if isinstance(value, dict):
                # Support nested access: {{var.key}}
                for nested_key, nested_value in self._flatten_dict(value, key):
                    text = text.replace(f'{{{{{nested_key}}}}}', str(nested_value))
            else:
                text = text.replace(f'{{{{{key}}}}}', str(value))

        # Replace webhook data
        for key, value in self.webhook_data.items():
            text = text.replace(f'{{{{webhook.{key}}}}}', str(value))

        return text

    def _flatten_dict(self, d: dict, prefix: str):
        """Flatten nested dict for interpolation"""
        items = [(prefix, d)]
        for key, value in d.items():
            new_key = f'{prefix}.{key}'
            if isinstance(value, dict):
                items.extend(self._flatten_dict(value, new_key))
            else:
                items.append((new_key, value))
        return items
```

### Variable Interpolation Examples

```python
# Built-in variables
context.interpolate("Current time: {{time}}")
# "Current time: 09:15:00"

# User variables
context.set_variable("quote", {"ltp": 625.50, "volume": 1000000})
context.interpolate("LTP is {{quote.ltp}}")
# "LTP is 625.5"

# Webhook data
# webhook_data = {"symbol": "RELIANCE", "action": "BUY"}
context.interpolate("Trade {{webhook.symbol}} with {{webhook.action}}")
# "Trade RELIANCE with BUY"
```

## NodeExecutor

Executes individual node operations.

```python
class NodeExecutor:
    def __init__(self, client: FlowOpenAlgoClient, context: WorkflowContext, logs: list):
        self.client = client
        self.context = context
        self.logs = logs

    # ========== Helper Methods ==========

    def get_str(self, data: dict, key: str, default: str = "") -> str:
        """Get string value with interpolation"""
        value = str(data.get(key, default) or default)
        return self.context.interpolate(value)

    def get_int(self, data: dict, key: str, default: int = 0) -> int:
        """Get integer value"""
        try:
            return int(data.get(key, default) or default)
        except (ValueError, TypeError):
            return default

    def get_float(self, data: dict, key: str, default: float = 0.0) -> float:
        """Get float value"""
        try:
            return float(data.get(key, default) or default)
        except (ValueError, TypeError):
            return default

    def get_bool(self, data: dict, key: str, default: bool = False) -> bool:
        """Get boolean value"""
        return bool(data.get(key, default))

    def store_output(self, node_data: dict, result: Any):
        """Store result in output variable if specified"""
        output_var = node_data.get("outputVariable")
        if output_var:
            self.context.set_variable(output_var, result)

    def log(self, message: str, level: str = "info"):
        """Add log entry"""
        self.logs.append({
            "time": datetime.now().isoformat(),
            "message": message,
            "level": level
        })

    # ========== Order Execution ==========

    def execute_place_order(self, node_data: dict) -> dict:
        """Execute place order node"""
        symbol = self.get_str(node_data, "symbol")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        quantity = self.get_int(node_data, "quantity", 1)
        product = self.get_str(node_data, "product", "MIS")
        price_type = self.get_str(node_data, "priceType", "MARKET")
        price = self.get_float(node_data, "price", 0)
        trigger_price = self.get_float(node_data, "triggerPrice", 0)

        if not symbol:
            return {"status": "error", "message": "Symbol is required"}

        self.log(f"Placing order: {action} {quantity} {symbol}.{exchange}")

        result = self.client.place_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            product=product,
            price_type=price_type,
            price=price,
            trigger_price=trigger_price
        )

        self.store_output(node_data, result)
        self.log(f"Order result: {result.get('status')} - {result.get('orderid', result.get('message'))}")

        return result

    def execute_smart_order(self, node_data: dict) -> dict:
        """Execute smart order (position-aware)"""
        symbol = self.get_str(node_data, "symbol")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        quantity = self.get_int(node_data, "quantity", 1)
        position_size = self.get_int(node_data, "positionSize", 0)
        product = self.get_str(node_data, "product", "MIS")
        price_type = self.get_str(node_data, "priceType", "MARKET")

        self.log(f"Smart order: {action} {symbol} qty={quantity} pos_size={position_size}")

        result = self.client.smart_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            position_size=position_size,
            product=product,
            price_type=price_type
        )

        self.store_output(node_data, result)
        return result

    # ========== Condition Execution ==========

    def execute_price_condition(self, node_data: dict, node_id: str) -> dict:
        """Execute price condition node"""
        symbol = self.get_str(node_data, "symbol")
        exchange = self.get_str(node_data, "exchange", "NSE")
        field = self.get_str(node_data, "field", "ltp")
        operator = self.get_str(node_data, "operator", ">")
        value = self.get_float(node_data, "value", 0)

        # Fetch current quote
        quote = self.client.get_quote(symbol, exchange)
        quote_data = quote.get("data", {})
        actual = float(quote_data.get(field, 0))

        # Evaluate condition
        result = self._evaluate_condition(actual, operator, value)

        # Store for edge routing
        self.context.set_condition_result(node_id, result)

        self.log(f"Price condition: {symbol}.{field} ({actual}) {operator} {value} = {result}")
        return {"result": result, "actual": actual, "expected": value}

    def execute_position_check(self, node_data: dict, node_id: str) -> dict:
        """Execute position check node"""
        symbol = self.get_str(node_data, "symbol")
        exchange = self.get_str(node_data, "exchange", "NSE")
        check_type = self.get_str(node_data, "checkType", "exists")
        threshold = self.get_int(node_data, "quantity", 0)

        # Get position
        position = self.client.get_open_position(symbol, exchange)
        quantity = abs(int(position.get("quantity", 0)))

        # Evaluate check
        if check_type == "exists":
            result = quantity != 0
        elif check_type == "quantity_gt":
            result = quantity > threshold
        elif check_type == "quantity_lt":
            result = quantity < threshold
        else:
            result = False

        self.context.set_condition_result(node_id, result)
        self.log(f"Position check: {symbol} qty={quantity} {check_type} = {result}")

        return {"result": result, "quantity": quantity}

    def execute_time_window(self, node_data: dict, node_id: str) -> dict:
        """Execute time window condition"""
        start_time = self.get_str(node_data, "startTime", "09:15")
        end_time = self.get_str(node_data, "endTime", "15:30")
        days = node_data.get("days", ["mon", "tue", "wed", "thu", "fri"])

        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day = now.strftime("%a").lower()

        in_time = start_time <= current_time <= end_time
        in_day = current_day in days

        result = in_time and in_day

        self.context.set_condition_result(node_id, result)
        self.log(f"Time window: {current_time} in [{start_time}-{end_time}], {current_day} in {days} = {result}")

        return {"result": result}

    def _evaluate_condition(self, actual: float, operator: str, expected: float) -> bool:
        """Evaluate comparison condition"""
        if operator == ">":
            return actual > expected
        elif operator == "<":
            return actual < expected
        elif operator == "==":
            return actual == expected
        elif operator == ">=":
            return actual >= expected
        elif operator == "<=":
            return actual <= expected
        elif operator == "!=":
            return actual != expected
        return False

    # ========== Data Fetching ==========

    def execute_get_quote(self, node_data: dict) -> dict:
        """Execute get quote node"""
        symbol = self.get_str(node_data, "symbol")
        exchange = self.get_str(node_data, "exchange", "NSE")

        result = self.client.get_quote(symbol, exchange)

        self.store_output(node_data, result.get("data", {}))
        self.log(f"Got quote: {symbol}.{exchange} LTP={result.get('data', {}).get('ltp')}")

        return result

    def execute_get_positions(self, node_data: dict) -> dict:
        """Execute get positions node"""
        result = self.client.get_positions()

        self.store_output(node_data, result.get("data", []))
        self.log(f"Got positions: {len(result.get('data', []))} positions")

        return result

    # ========== Utility Operations ==========

    def execute_variable(self, node_data: dict) -> dict:
        """Execute variable node (set/get/math)"""
        operation = self.get_str(node_data, "operation", "set")
        var_name = self.get_str(node_data, "variableName")
        value = node_data.get("value")
        source_var = self.get_str(node_data, "sourceVariable")

        if operation == "set":
            self.context.set_variable(var_name, value)
            self.log(f"Set {var_name} = {value}")

        elif operation == "get":
            result = self.context.get_variable(var_name)
            return {"value": result}

        elif operation in ["add", "subtract", "multiply", "divide"]:
            source_value = self.context.get_variable(source_var, 0)
            if operation == "add":
                result = float(source_value) + float(value)
            elif operation == "subtract":
                result = float(source_value) - float(value)
            elif operation == "multiply":
                result = float(source_value) * float(value)
            elif operation == "divide":
                result = float(source_value) / float(value) if float(value) != 0 else 0

            self.context.set_variable(var_name, result)
            self.log(f"Calculated {var_name} = {result}")

        elif operation == "parse_json":
            import json
            try:
                parsed = json.loads(str(value))
                self.context.set_variable(var_name, parsed)
                self.log(f"Parsed JSON into {var_name}")
            except json.JSONDecodeError as e:
                self.log(f"JSON parse error: {e}", "error")
                return {"status": "error", "message": str(e)}

        return {"status": "success"}

    def execute_delay(self, node_data: dict) -> dict:
        """Execute delay node"""
        import time
        seconds = self.get_float(node_data, "seconds", 1)

        self.log(f"Waiting {seconds} seconds...")
        time.sleep(seconds)
        self.log(f"Delay complete")

        return {"status": "success"}

    def execute_log(self, node_data: dict) -> dict:
        """Execute log node"""
        message = self.get_str(node_data, "message")
        level = self.get_str(node_data, "level", "info")

        self.log(message, level)
        return {"status": "success", "message": message}

    def execute_telegram_alert(self, node_data: dict) -> dict:
        """Execute telegram alert node"""
        message = self.get_str(node_data, "message")

        result = self.client.send_telegram_alert(message)
        self.log(f"Telegram alert: {message[:50]}...")

        return result
```

## Workflow Execution

Main execution function.

```python
def execute_workflow(
    workflow_id: int,
    webhook_data: dict = None,
    api_key: str = None
) -> dict:
    """Execute a complete workflow"""

    # 1. Load workflow from database
    workflow = get_workflow(workflow_id)
    if not workflow:
        return {"status": "error", "message": "Workflow not found"}

    nodes = workflow.nodes
    edges = workflow.edges
    api_key = api_key or workflow.api_key

    if not api_key:
        return {"status": "error", "message": "No API key available"}

    # 2. Create execution context
    context = WorkflowContext(webhook_data=webhook_data)
    logs = []

    # 3. Create executor with OpenAlgo client
    client = FlowOpenAlgoClient(api_key)
    executor = NodeExecutor(client, context, logs)

    # 4. Build edge maps for traversal
    edge_map = {}  # source_id -> [edges]
    incoming_edge_map = {}  # target_id -> [edges]

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")

        if source not in edge_map:
            edge_map[source] = []
        edge_map[source].append(edge)

        if target not in incoming_edge_map:
            incoming_edge_map[target] = []
        incoming_edge_map[target].append(edge)

    # 5. Find trigger nodes (entry points)
    trigger_types = ["start", "webhookTrigger", "priceAlert", "httpRequest"]
    trigger_nodes = [n for n in nodes if n.get("type") in trigger_types]

    # 6. Execute from each trigger
    try:
        for trigger in trigger_nodes:
            execute_node_chain(
                node_id=trigger["id"],
                nodes=nodes,
                edge_map=edge_map,
                incoming_edge_map=incoming_edge_map,
                executor=executor,
                context=context,
                logs=logs,
                executed_nodes=set()
            )

        return {
            "status": "success",
            "logs": logs,
            "variables": context.variables
        }

    except Exception as e:
        logs.append({
            "time": datetime.now().isoformat(),
            "message": f"Execution error: {str(e)}",
            "level": "error"
        })
        return {
            "status": "error",
            "message": str(e),
            "logs": logs
        }
```

## Node Chain Execution

Recursive execution with edge following.

```python
def execute_node_chain(
    node_id: str,
    nodes: list,
    edge_map: dict,
    incoming_edge_map: dict,
    executor: NodeExecutor,
    context: WorkflowContext,
    logs: list,
    executed_nodes: set
):
    """Execute a node and follow outgoing edges"""

    # Prevent re-execution
    if node_id in executed_nodes:
        return
    executed_nodes.add(node_id)

    # Find node
    node = next((n for n in nodes if n["id"] == node_id), None)
    if not node:
        return

    node_type = node.get("type")
    node_data = node.get("data", {})

    logs.append({
        "time": datetime.now().isoformat(),
        "message": f"Executing node: {node_type}",
        "level": "info"
    })

    # Execute based on type
    result = None

    # Trigger nodes
    if node_type == "start":
        result = {"status": "success", "message": "Workflow started"}
    elif node_type == "webhookTrigger":
        result = {"status": "success", "data": context.webhook_data}

    # Action nodes
    elif node_type == "placeOrder":
        result = executor.execute_place_order(node_data)
    elif node_type == "smartOrder":
        result = executor.execute_smart_order(node_data)
    elif node_type == "optionsOrder":
        result = executor.execute_options_order(node_data)
    elif node_type == "cancelAllOrders":
        result = executor.execute_cancel_all_orders(node_data)
    elif node_type == "closePositions":
        result = executor.execute_close_positions(node_data)

    # Condition nodes
    elif node_type == "priceCondition":
        result = executor.execute_price_condition(node_data, node_id)
    elif node_type == "positionCheck":
        result = executor.execute_position_check(node_data, node_id)
    elif node_type == "fundCheck":
        result = executor.execute_fund_check(node_data, node_id)
    elif node_type == "timeWindow":
        result = executor.execute_time_window(node_data, node_id)
    elif node_type in ["andGate", "orGate", "notGate"]:
        result = executor.execute_logic_gate(node_data, node_id, node_type, incoming_edge_map, context)

    # Data nodes
    elif node_type == "getQuote":
        result = executor.execute_get_quote(node_data)
    elif node_type == "getDepth":
        result = executor.execute_get_depth(node_data)
    elif node_type == "positionBook":
        result = executor.execute_get_positions(node_data)
    elif node_type == "funds":
        result = executor.execute_get_funds(node_data)
    elif node_type == "history":
        result = executor.execute_get_history(node_data)

    # Utility nodes
    elif node_type == "variable":
        result = executor.execute_variable(node_data)
    elif node_type == "delay":
        result = executor.execute_delay(node_data)
    elif node_type == "log":
        result = executor.execute_log(node_data)
    elif node_type == "telegramAlert":
        result = executor.execute_telegram_alert(node_data)

    # Follow outgoing edges
    outgoing_edges = edge_map.get(node_id, [])

    for edge in outgoing_edges:
        target_id = edge.get("target")
        source_handle = edge.get("sourceHandle")

        # For conditional nodes, check which path to follow
        if source_handle in ["true", "false"]:
            condition_result = context.get_condition_result(node_id)
            should_follow = (source_handle == "true" and condition_result) or \
                          (source_handle == "false" and not condition_result)

            if not should_follow:
                continue

        # Execute next node
        execute_node_chain(
            node_id=target_id,
            nodes=nodes,
            edge_map=edge_map,
            incoming_edge_map=incoming_edge_map,
            executor=executor,
            context=context,
            logs=logs,
            executed_nodes=executed_nodes
        )
```

## FlowOpenAlgoClient

Wraps internal OpenAlgo APIs.

```python
class FlowOpenAlgoClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def place_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        product: str = "MIS",
        price_type: str = "MARKET",
        price: float = 0,
        trigger_price: float = 0
    ) -> dict:
        """Place an order using internal API"""
        from services.place_order_service import place_order_service

        return place_order_service(
            api_key=self.api_key,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            product=product,
            price_type=price_type,
            price=price,
            trigger_price=trigger_price
        )

    def smart_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        position_size: int,
        product: str = "MIS",
        price_type: str = "MARKET"
    ) -> dict:
        """Place smart order (position-aware)"""
        from services.smart_order_service import smart_order_service

        return smart_order_service(
            api_key=self.api_key,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            position_size=position_size,
            product=product,
            price_type=price_type
        )

    def get_quote(self, symbol: str, exchange: str) -> dict:
        """Get current quote"""
        from services.quote_service import get_quotes_service

        return get_quotes_service(
            api_key=self.api_key,
            symbol=symbol,
            exchange=exchange
        )

    def get_positions(self) -> dict:
        """Get all positions"""
        from services.position_service import get_positions_service

        return get_positions_service(api_key=self.api_key)

    def get_open_position(self, symbol: str, exchange: str) -> dict:
        """Get position for specific symbol"""
        from services.position_service import get_open_position_service

        return get_open_position_service(
            api_key=self.api_key,
            symbol=symbol,
            exchange=exchange
        )

    def send_telegram_alert(self, message: str) -> dict:
        """Send telegram notification"""
        from services.telegram_service import send_telegram_message

        return send_telegram_message(message)
```

## Scheduling

APScheduler integration for scheduled workflows.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# IST timezone for Indian markets
IST = pytz.timezone('Asia/Kolkata')

scheduler = BackgroundScheduler(daemon=True, timezone=IST)

def schedule_workflow(workflow_id: int, schedule_config: dict) -> str:
    """Schedule a workflow for automatic execution"""
    schedule_type = schedule_config.get("scheduleType", "daily")
    time_str = schedule_config.get("time", "09:15")
    days = schedule_config.get("days", ["mon", "tue", "wed", "thu", "fri"])

    hour, minute = map(int, time_str.split(":"))

    if schedule_type == "daily":
        # Run daily at specified time
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=",".join(days[:3]),  # APScheduler format
            timezone=IST
        )

    elif schedule_type == "interval":
        interval_minutes = schedule_config.get("intervalMinutes", 5)
        from apscheduler.triggers.interval import IntervalTrigger
        trigger = IntervalTrigger(minutes=interval_minutes)

    elif schedule_type == "once":
        from apscheduler.triggers.date import DateTrigger
        run_date = schedule_config.get("runDate")
        trigger = DateTrigger(run_date=run_date, timezone=IST)

    # Add job
    job_id = f"workflow_{workflow_id}"
    scheduler.add_job(
        func=execute_workflow,
        trigger=trigger,
        args=[workflow_id],
        id=job_id,
        replace_existing=True
    )

    return job_id

def unschedule_workflow(job_id: str):
    """Remove scheduled workflow"""
    scheduler.remove_job(job_id)
```

## Database Models

```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from database import Base

class FlowWorkflow(Base):
    __tablename__ = 'flow_workflows'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    nodes = Column(JSON, default=[])
    edges = Column(JSON, default=[])
    is_active = Column(Boolean, default=False)
    schedule_job_id = Column(String(255))
    webhook_token = Column(String(255), unique=True)
    webhook_secret = Column(String(255))
    webhook_enabled = Column(Boolean, default=False)
    webhook_auth_type = Column(String(50), default='payload')
    api_key = Column(String(255))  # Stored when activated
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class FlowWorkflowExecution(Base):
    __tablename__ = 'flow_workflow_executions'

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('flow_workflows.id'))
    status = Column(String(50))  # pending, running, completed, failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    logs = Column(JSON, default=[])
    error = Column(Text)
```

## Webhook Handler

```python
from flask import Blueprint, request, jsonify

flow_bp = Blueprint('flow', __name__)

@flow_bp.route('/flow/webhook/<token>', methods=['POST'])
def handle_webhook(token: str):
    """Handle incoming webhook for workflow execution"""

    # Find workflow by token
    workflow = FlowWorkflow.query.filter_by(
        webhook_token=token,
        webhook_enabled=True
    ).first()

    if not workflow:
        return jsonify({"status": "error", "message": "Invalid webhook token"}), 404

    # Verify secret
    payload = request.get_json() or {}

    if workflow.webhook_auth_type == 'payload':
        # Secret in payload
        provided_secret = payload.get('secret')
        if provided_secret != workflow.webhook_secret:
            return jsonify({"status": "error", "message": "Invalid secret"}), 401

    elif workflow.webhook_auth_type == 'url':
        # Secret in URL parameter
        provided_secret = request.args.get('secret')
        if provided_secret != workflow.webhook_secret:
            return jsonify({"status": "error", "message": "Invalid secret"}), 401

    # Execute workflow
    result = execute_workflow(
        workflow_id=workflow.id,
        webhook_data=payload,
        api_key=workflow.api_key
    )

    # Store execution record
    execution = FlowWorkflowExecution(
        workflow_id=workflow.id,
        status=result.get('status'),
        started_at=datetime.now(),
        completed_at=datetime.now(),
        logs=result.get('logs', []),
        error=result.get('message') if result.get('status') == 'error' else None
    )
    db.session.add(execution)
    db.session.commit()

    return jsonify(result)
```

## Error Handling

```python
class FlowExecutionError(Exception):
    """Custom exception for flow execution errors"""
    pass

def safe_execute_node(executor: NodeExecutor, node_type: str, node_data: dict, node_id: str = None) -> dict:
    """Execute node with error handling"""
    try:
        # Map node type to executor method
        method_name = f"execute_{node_type}"
        if hasattr(executor, method_name):
            method = getattr(executor, method_name)
            if node_id:
                return method(node_data, node_id)
            return method(node_data)
        else:
            return {"status": "error", "message": f"Unknown node type: {node_type}"}

    except Exception as e:
        executor.log(f"Error executing {node_type}: {str(e)}", "error")
        return {"status": "error", "message": str(e)}
```
