# utils/python_strategy_manager.py
import json
import os
import subprocess
import glob
import signal # For sending signals to processes
import ast # For parsing Python files
import inspect # To analyze function signatures
import csv # For CSV manipulation

STRATEGY_LIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'strategy_live')
STRATEGY_STATE_FILE = os.path.join(STRATEGY_LIVE_DIR, 'strategy_states.json')
PYTHON_EXECUTABLE = 'python' # Or specify absolute path to python interpreter if needed

EXCLUDED_UI_PARAMS = {
    "STRATEGY_NAME_SPECIFIC", # Often derived from filename, or core identity
    "API_KEY_SPECIFIC",       # System/broker credential
    "HOST_URL_SPECIFIC",      # System/broker credential
    "WS_URL_SPECIFIC",        # System/broker credential
    "STOCKS_CSV_NAME_SPECIFIC" # Usually a core setting, not a logic param
    # Other potential candidates: TIMEFRAME_SPECIFIC, PRODUCT_TYPE_SPECIFIC if they are considered
    # system-level rather than tweakable strategy logic for a given script.
    # For now, keeping exclusion list minimal to what's clearly system/identity.
}

LOGS_SUBDIR = "logs" # Define logs subdirectory name

def _ensure_strategy_dir_exists():
    """Ensure the base strategy directory and logs subdirectory exist."""
    os.makedirs(STRATEGY_LIVE_DIR, exist_ok=True)
    log_dir = os.path.join(STRATEGY_LIVE_DIR, LOGS_SUBDIR)
    os.makedirs(log_dir, exist_ok=True)

def _load_strategy_states():
    """Loads strategy states from the JSON file."""
    _ensure_strategy_dir_exists()
    if not os.path.exists(STRATEGY_STATE_FILE):
        return {}
    try:
        with open(STRATEGY_STATE_FILE, 'r', encoding='utf-8') as f: # Added encoding
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def _save_strategy_states(states):
    """Saves strategy states to the JSON file."""
    _ensure_strategy_dir_exists()
    try:
        with open(STRATEGY_STATE_FILE, 'w', encoding='utf-8') as f: # Added encoding
            json.dump(states, f, indent=4)
    except IOError:
        print(f"Error: Could not save strategy states to {STRATEGY_STATE_FILE}")
        pass

def get_strategy_files():
    """Returns a list of strategy script basenames in the strategy_live folder."""
    _ensure_strategy_dir_exists()
    files = []
    if not os.path.isdir(STRATEGY_LIVE_DIR):
        return files
    for f_path in glob.glob(os.path.join(STRATEGY_LIVE_DIR, '*_live.py')):
        if os.path.basename(f_path) != '__init__.py':
             files.append(os.path.basename(f_path))
    return files

def get_all_strategy_statuses():
    """
    Gets the status of all strategies, combining file presence with stored state.
    Returns a dictionary where keys are strategy file names and values are dicts
    with 'status' ('active', 'inactive', 'error') and 'pid'.
    """
    states = _load_strategy_states()
    statuses = {}
    strategy_files = get_strategy_files()
    active_states_updated = False
    for strategy_file in strategy_files:
        state_info = states.get(strategy_file, {'active': False, 'pid': None})
        pid = state_info.get('pid')
        is_running = False
        if pid:
            try: os.kill(pid, 0); is_running = True
            except OSError: is_running = False

        if state_info.get('active') and is_running:
            statuses[strategy_file] = {'status': 'active', 'pid': pid}
        elif state_info.get('active') and not is_running:
            statuses[strategy_file] = {'status': 'error', 'pid': None}
            states[strategy_file] = {'active': False, 'pid': None}
            active_states_updated = True
        else:
            statuses[strategy_file] = {'status': 'inactive', 'pid': None}
            if states.get(strategy_file, {}).get('active'):
                states[strategy_file] = {'active': False, 'pid': None}
                active_states_updated = True
    if active_states_updated:
        _save_strategy_states(states)
    return statuses

def activate_strategy(strategy_file):
    states = _load_strategy_states()
    if strategy_file not in get_strategy_files():
        return False, "Strategy file not found."
    current_status = get_all_strategy_statuses().get(strategy_file)
    if current_status and current_status['status'] == 'active':
         return True, f"Strategy {strategy_file} already active and running with PID {current_status['pid']}."
    strategy_path = os.path.join(STRATEGY_LIVE_DIR, strategy_file)
    try:
        log_dir = os.path.join(STRATEGY_LIVE_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{strategy_file.replace('.py', '')}.log")
        with open(log_file_path, 'a') as log_file:
            process = subprocess.Popen(
                [PYTHON_EXECUTABLE, "-u", strategy_path], cwd=STRATEGY_LIVE_DIR,
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                start_new_session=True if os.name != 'nt' else False)
        states[strategy_file] = {'active': True, 'pid': process.pid}
        _save_strategy_states(states)
        return True, f"Strategy {strategy_file} activated with PID {process.pid}. Logging to {log_file_path}"
    except Exception as e:
        states[strategy_file] = {'active': False, 'pid': None}
        _save_strategy_states(states)
        return False, f"Failed to activate {strategy_file}: {str(e)}"

def deactivate_strategy(strategy_file):
    states = _load_strategy_states()
    state_info = states.get(strategy_file)
    if not state_info or not state_info.get('active'):
        states[strategy_file] = {'active': False, 'pid': None}
        _save_strategy_states(states)
        return True, f"Strategy {strategy_file} is already inactive or not found in state."
    pid = state_info.get('pid')
    if pid:
        try:
            os.kill(pid, 0)
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], check=True, capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError: print(f"Process {pid} for {strategy_file} not found (already exited?).")
        except subprocess.CalledProcessError as e: print(f"Failed to taskkill {pid} for {strategy_file}: {e.stderr.decode()}")
        except Exception as e: print(f"Error deactivating {strategy_file} (PID: {pid}): {e}")
    states[strategy_file] = {'active': False, 'pid': None}
    _save_strategy_states(states)
    return True, f"Strategy {strategy_file} (PID: {pid if pid else 'N/A'}) requested to stop."

def _get_params_from_global_constants(strategy_path):
    """
    Parses a Python file and extracts top-level global constants
    (simple assignments like NAME = value), excluding system-defined ones.
    """
    constants = {}
    try:
        with open(strategy_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    param_name = node.targets[0].id
                    if param_name in EXCLUDED_UI_PARAMS: # Check against exclusion list
                        continue
                    try:
                        if isinstance(node.value, ast.Constant): # Python 3.8+
                            constants[param_name] = node.value.value
                        # Add elif for older Python versions (ast.Str, ast.Num, ast.NameConstant) if necessary
                    except ValueError: pass # Skip if value cannot be evaluated
    except Exception as e:
        print(f"Error parsing global constants from {os.path.basename(strategy_path)}: {e}") # Log error
    return constants

def _get_default_params_from_init(strategy_path): # Kept for potential future use or complex defaults
    defaults = {}
    try:
        with open(strategy_path, 'r', encoding='utf-8') as f: content = f.read() # Added encoding
        tree = ast.parse(content)
        for node_class in ast.walk(tree):
            if isinstance(node_class, ast.ClassDef):
                if any(isinstance(base, ast.Name) and base.id == 'BaseStrategy' for base in node_class.bases):
                    for item in node_class.body:
                        if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                            args = item.args
                            num_defaults = len(args.defaults)
                            for i in range(num_defaults):
                                arg_idx = len(args.args) - num_defaults + i
                                arg_name = args.args[arg_idx].arg
                                if arg_name not in ['self', 'strategy_name', 'api_key', 'host_url', 'ws_url']: # Exclude base knowns
                                    try:
                                        if isinstance(args.defaults[i], ast.Constant): # Python 3.8+
                                            defaults[arg_name] = args.defaults[i].value
                                        # Add elif for older Python versions if necessary
                                    except ValueError: pass
                            # Handle kwonlyargs
                            for i, kwarg_node in enumerate(args.kwonlyargs):
                                if args.kw_defaults[i] is not None:
                                    arg_name = kwarg_node.arg
                                    if arg_name not in ['self', 'strategy_name', 'api_key', 'host_url', 'ws_url']:
                                        try:
                                            if isinstance(args.kw_defaults[i], ast.Constant):
                                                defaults[arg_name] = args.kw_defaults[i].value
                                        except ValueError: pass
                            break # Found __init__
                    if defaults: break # Found relevant class and __init__
        return defaults
    except Exception as e:
        print(f"Error parsing __init__ for {os.path.basename(strategy_path)}: {e}")
        return {}

def get_strategy_config_path(strategy_file):
    return os.path.join(STRATEGY_LIVE_DIR, strategy_file.replace('_live.py', '_config.json'))

def get_strategy_parameters(strategy_file):
    strategy_path = os.path.join(STRATEGY_LIVE_DIR, strategy_file)
    if not os.path.exists(strategy_path):
        return None, None, "Strategy file not found."

    params = _get_params_from_global_constants(strategy_path)
    # init_params = _get_default_params_from_init(strategy_path) # Optionally overlay if needed
    # params.update(init_params)

    config_path = get_strategy_config_path(strategy_file)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                saved_params = json.load(f)
            params.update(saved_params)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading config {config_path}: {e}")

    class_docstring = None
    try:
        with open(strategy_path, 'r', encoding='utf-8') as f: content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == 'BaseStrategy' for b in node.bases):
                docstring_node = ast.get_docstring(node)
                if docstring_node: class_docstring = docstring_node
                break
    except Exception as e: print(f"Error parsing docstring for {strategy_file}: {e}")

    description_to_use = params.get("description", class_docstring)
    return params, description_to_use, None

def save_strategy_parameters(strategy_file, parameters):
    config_path = get_strategy_config_path(strategy_file)

    KEY_TRANSFORMATION_MAP = {
        # BaseStrategy attributes
        "PRODUCT_TYPE_SPECIFIC": "product_type",
        "TIMEFRAME_SPECIFIC": "timeframe",
        "STRATEGY_START_TIME_SPECIFIC": "strategy_start_time_str",
        "STRATEGY_END_TIME_SPECIFIC": "strategy_end_time_str",
        "JOURNALING_TIME_SPECIFIC": "journaling_time_str",
        "RE_ENTRY_WAIT_MINUTES_SPECIFIC": "re_entry_wait_minutes",
        "HISTORY_DAYS_TO_FETCH_SPECIFIC": "history_days_to_fetch",
        "LOOP_SLEEP_SECONDS_SPECIFIC": "loop_sleep_seconds",
        "USE_STOPLOSS_SPECIFIC": "use_stoploss",
        "STOPLOSS_PERCENT_SPECIFIC": "stoploss_percent",
        "USE_TARGET_SPECIFIC": "use_target",
        "TARGET_PERCENT_SPECIFIC": "target_percent",
        "ORDER_CONFIRMATION_ATTEMPTS_SPECIFIC": "order_confirmation_attempts",
        "ORDER_CONFIRMATION_DELAY_SECONDS_SPECIFIC": "order_confirmation_delay_seconds",
        # Strategy-specific parameters (matching .get() calls in derived strategies)
        "ENTRY_LOOKBACK_SPECIFIC": "ENTRY_LOOKBACK", # As used by breakout_2nd_stage.py
        "EXIT_LOOKBACK_SPECIFIC": "EXIT_LOOKBACK"   # As used by breakout_2nd_stage.py
        # Note: The UI form fields in templates/python_strategy/details.html
        # should ideally have names that result in these "SPECIFIC" keys appearing
        # in the `parameters` dict received by this function.
    }

    transformed_parameters = {}
    for key, value in parameters.items():
        # Use the mapped key if it exists, otherwise use the original key.
        # This also handles parameters that don't need transformation (e.g., 'description').
        new_key = KEY_TRANSFORMATION_MAP.get(key, key)
        transformed_parameters[new_key] = value

    # Ensure 'description_from_code' is not saved if it was part of params from get_strategy_parameters
    # The blueprint already tries to remove this, but an extra check here is fine.
    if 'description_from_code' in transformed_parameters:
        del transformed_parameters['description_from_code']

    try:
        # Ensure the directory exists (important if a strategy is new and has no config yet)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(transformed_parameters, f, indent=4)
        return True, "Parameters saved successfully."
    except (IOError, TypeError) as e:
        return False, f"Error saving parameters: {e}"

def get_strategy_stocks_csv_path(strategy_file):
    params, _, _ = get_strategy_parameters(strategy_file)
    default_stocks_csv_name = "stocks.csv"
    stocks_csv_name = params.get('STOCKS_CSV_NAME_SPECIFIC') or \
                      params.get('stocks_csv_name', default_stocks_csv_name)
    return os.path.join(STRATEGY_LIVE_DIR, os.path.basename(stocks_csv_name))

def get_strategy_stocks(strategy_file):
    csv_path = get_strategy_stocks_csv_path(strategy_file) # This should point to shared 'stocks.csv'
    strategy_specific_stocks = []
    error_message = None # Initialize error_message

    if not os.path.exists(csv_path):
        return [], f"Stock file {os.path.basename(csv_path)} not found." # Return empty list and error message

    try:
        # Derive the strategy_id key from the strategy_file name (e.g., "MyStrategy_live.py" -> "MyStrategy")
        current_strategy_key = strategy_file.replace('_live.py', '').replace('.py', '')

        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # Define the set of headers that are absolutely required for the function to operate correctly.
            # 'strategy_id' is crucial for filtering.
            required_headers = {'symbol', 'exchange', 'max_fund', 'strategy_id'}

            if not reader.fieldnames:
                # No headers in the CSV (e.g., empty file or just created with no header yet)
                # This isn't an error for this function's purpose if it's just an empty setup.
                # The save function should ensure headers are written.
                # We can inform that no stocks are configured.
                error_message = f"Stock file {os.path.basename(csv_path)} is empty or has no headers."
                return [], error_message

            if not required_headers.issubset(reader.fieldnames):
                # Headers are present, but not all required ones. This is an issue.
                missing_cols = required_headers - set(reader.fieldnames)
                error_message = f"Stock file {os.path.basename(csv_path)} is missing required columns: {', '.join(missing_cols)}."
                return [], error_message

            for row_number, row in enumerate(reader, 1): # Start row count from 1 for messages
                # Filter: only include rows where 'strategy_id' matches the current_strategy_key
                if row.get('strategy_id') == current_strategy_key:
                    # Add the 'id' field used by the UI (e.g., for edit/delete operations)
                    # Ensure symbol and exchange exist before creating id to prevent None_None
                    symbol = row.get('symbol')
                    exchange = row.get('exchange')
                    if symbol and exchange:
                        row['id'] = f"{symbol}_{exchange}"
                    else:
                        # This row is malformed for the current strategy, skip it or log warning
                        print(f"Warning: Row {row_number} for strategy {current_strategy_key} in {os.path.basename(csv_path)} is missing symbol or exchange. Skipping.")
                        continue
                    strategy_specific_stocks.append(row)

            if not strategy_specific_stocks and not error_message: # Check error_message to avoid overwriting previous file issue messages
                # This is not an error, but information that no stocks are configured for THIS strategy.
                error_message = f"No stocks currently configured for strategy '{current_strategy_key}' in {os.path.basename(csv_path)}."
                # Return empty list and this message. The UI can decide how to display this.

        return strategy_specific_stocks, error_message # error_message will be None if stocks were found and no other issues.

    except Exception as e:
        return [], f"Error reading stock file {os.path.basename(csv_path)}: {str(e)}"

def save_strategy_stocks(strategy_file, stocks_data_for_current_strategy):
    # stocks_data_for_current_strategy is a list of dicts provided by the UI routes,
    # representing the desired state for *this specific strategy's* stocks.
    # The blueprint should ensure that 'strategy_id' is correctly populated on these dicts,
    # or at least that they are indeed only for the current strategy.

    csv_path = get_strategy_stocks_csv_path(strategy_file) # This should point to the shared 'stocks.csv'
    # IMPORTANT: Define all columns that should be in the CSV, including 'strategy_id'
    fieldnames = ['symbol', 'exchange', 'max_fund', 'strategy_id']

    # Derive the strategy_id key from the strategy_file name (e.g., "MyStrategy_live.py" -> "MyStrategy")
    current_strategy_key = strategy_file.replace('_live.py', '').replace('.py', '')

    all_stocks_from_csv = []
    try:
        # Step 1: Read all existing stocks from the CSV, if it exists, to preserve other strategies' data.
        if os.path.exists(csv_path):
            with open(csv_path, 'r', newline='', encoding='utf-8') as f_read:
                reader = csv.DictReader(f_read)
                # Check if headers are present and contain AT LEAST our core fields.
                # If strategy_id is missing, rows without it won't be associated with any strategy.
                if reader.fieldnames: # Ensure file is not empty and has headers
                    for row in reader:
                        all_stocks_from_csv.append(row)
                # If the file is empty or headers are missing, all_stocks_from_csv remains empty.

        # Step 2: Filter out any old stocks for the *current* strategy from what we read.
        # This ensures we are replacing the current strategy's stock list entirely with
        # the new data passed in `stocks_data_for_current_strategy`.
        other_strategy_stocks = []
        for stock in all_stocks_from_csv:
            # Only keep stocks that DO NOT belong to the current strategy key.
            # If strategy_id is missing in a row, it's treated as not belonging to current_strategy_key.
            if stock.get('strategy_id') != current_strategy_key:
                other_strategy_stocks.append(stock)

        # Step 3: Prepare the stocks for the current strategy, ensuring their strategy_id is correctly set.
        # The `stocks_data_for_current_strategy` comes from the UI and should represent the full list
        # of stocks intended for *this* strategy.
        final_stocks_for_this_strategy = []
        for stock_entry in stocks_data_for_current_strategy:
            entry_copy = stock_entry.copy() # Work with a copy
            entry_copy['strategy_id'] = current_strategy_key # Explicitly set/overwrite strategy_id
            final_stocks_for_this_strategy.append(entry_copy)

        # Step 4: Combine the preserved stocks from other strategies with the new/updated stocks for the current strategy.
        combined_stocks_to_write = other_strategy_stocks + final_stocks_for_this_strategy

        # Step 5: Write the combined list back to the CSV. This overwrites the old file.
        os.makedirs(os.path.dirname(csv_path), exist_ok=True) # Ensure directory exists
        with open(csv_path, 'w', newline='', encoding='utf-8') as f_write:
            writer = csv.DictWriter(f_write, fieldnames=fieldnames, extrasaction='ignore') # Ignore extra fields in dicts if any
            writer.writeheader()
            for stock_dict in combined_stocks_to_write:
                writer.writerow(stock_dict) # Write only fields specified in fieldnames

        return True, "Stocks saved successfully."

    except Exception as e:
        return False, f"Error saving stock file {os.path.basename(csv_path)}: {str(e)}"


def get_strategy_log_path(strategy_file):
    """
    Constructs the expected path to a strategy's log file.
    Example: my_strategy_live.py -> strategy_live/logs/my_strategy_live.log
             my_strategy.py -> strategy_live/logs/my_strategy.log
    """
    _ensure_strategy_dir_exists() # Ensures strategy_live and strategy_live/logs exist

    # Remove .py extension and add .log
    if strategy_file.endswith(".py"):
        base_name_with_live_preserved = strategy_file[:-3] # Remove .py
    else:
        # Should not happen if called with a .py file, but as a fallback
        base_name_with_live_preserved = strategy_file

    log_file_name = f"{base_name_with_live_preserved}.log"

    return os.path.join(STRATEGY_LIVE_DIR, LOGS_SUBDIR, log_file_name)

def read_strategy_log(strategy_file, tail_lines=200):
    """
    Reads the last N lines from a strategy's log file.
    Returns the content as a single string, or an error message.
    """
    log_path = get_strategy_log_path(strategy_file)

    if not os.path.exists(log_path):
        return f"Log file not found at: {log_path}"

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if tail_lines and len(lines) > tail_lines:
            log_content = "".join(lines[-tail_lines:])
        else:
            log_content = "".join(lines)

        if not log_content.strip():
            return "Log file is empty."

        return log_content
    except Exception as e:
        return f"Error reading log file {log_path}: {str(e)}"