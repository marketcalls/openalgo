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

def _ensure_strategy_dir_exists():
    """Ensures the strategy_live directory exists."""
    os.makedirs(STRATEGY_LIVE_DIR, exist_ok=True)

def _load_strategy_states():
    """Loads strategy states from the JSON file."""
    _ensure_strategy_dir_exists()
    if not os.path.exists(STRATEGY_STATE_FILE):
        return {}
    try:
        with open(STRATEGY_STATE_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def _save_strategy_states(states):
    """Saves strategy states to the JSON file."""
    _ensure_strategy_dir_exists()
    try:
        with open(STRATEGY_STATE_FILE, 'w') as f:
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
            try:
                os.kill(pid, 0)
                is_running = True
            except OSError:
                is_running = False

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
    """Activates a strategy by running its script."""
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
        with open(log_file_path, 'ab') as log_file:
            process = subprocess.Popen(
                [PYTHON_EXECUTABLE, strategy_path],
                cwd=STRATEGY_LIVE_DIR,
                stdout=log_file, stderr=log_file,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                start_new_session=True if os.name != 'nt' else False
            )
        states[strategy_file] = {'active': True, 'pid': process.pid}
        _save_strategy_states(states)
        return True, f"Strategy {strategy_file} activated with PID {process.pid}. Logging to {log_file_path}"
    except Exception as e:
        states[strategy_file] = {'active': False, 'pid': None}
        _save_strategy_states(states)
        return False, f"Failed to activate {strategy_file}: {str(e)}"

def deactivate_strategy(strategy_file):
    """Deactivates a strategy by terminating its process."""
    states = _load_strategy_states()
    state_info = states.get(strategy_file)
    if not state_info or not state_info.get('active'):
        states[strategy_file] = {'active': False, 'pid': None}
        _save_strategy_states(states)
        return True, f"Strategy {strategy_file} is already inactive or was not found in the state file."
    pid = state_info.get('pid')
    if pid:
        try:
            os.kill(pid, 0)
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], check=True, capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError:
            print(f"Process with PID {pid} for strategy {strategy_file} not found. It might have already exited.")
        except subprocess.CalledProcessError as e:
             print(f"Failed to terminate process {pid} for {strategy_file} using taskkill: {e.stderr.decode()}")
        except Exception as e:
            print(f"An unexpected error occurred during deactivation of {strategy_file} (PID: {pid}): {e}")
    states[strategy_file] = {'active': False, 'pid': None}
    _save_strategy_states(states)
    return True, f"Strategy {strategy_file} (PID: {pid if pid else 'N/A'}) has been requested to stop."

def _get_default_params_from_init(strategy_path):
    defaults = {}
    try:
        with open(strategy_path, 'r') as f: content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                base_strategy_parent = any(isinstance(base, ast.Name) and base.id == 'BaseStrategy' for base in node.bases)
                if not base_strategy_parent: continue
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                        args = item.args
                        num_defaults = len(args.defaults)
                        for i in range(num_defaults):
                            arg_index = len(args.args) - num_defaults + i
                            arg_name = args.args[arg_index].arg
                            if arg_name not in ['self', 'strategy_name', 'api_key', 'host_url', 'ws_url']:
                                try:
                                    defaults[arg_name] = ast.literal_eval(args.defaults[i])
                                except (ValueError, SyntaxError):
                                    if isinstance(args.defaults[i], ast.Name): defaults[arg_name] = args.defaults[i].id
                                    elif isinstance(args.defaults[i], ast.Constant): defaults[arg_name] = args.defaults[i].value
                        break
                if defaults: break
        return defaults
    except Exception as e:
        print(f"Error parsing __init__ for {os.path.basename(strategy_path)}: {e}")
        return {}

def get_strategy_config_path(strategy_file):
    return os.path.join(STRATEGY_LIVE_DIR, strategy_file.replace('_live.py', '_config.json'))

def get_strategy_parameters(strategy_file):
    """
    Gets strategy parameters and class docstring.
    """
    strategy_path = os.path.join(STRATEGY_LIVE_DIR, strategy_file)
    if not os.path.exists(strategy_path):
        return None, None, "Strategy file not found."

    params = _get_default_params_from_init(strategy_path)
    class_docstring = None
    try:
        with open(strategy_path, 'r') as f: content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if any(isinstance(base, ast.Name) and base.id == 'BaseStrategy' for base in node.bases):
                    docstring_node = ast.get_docstring(node)
                    if docstring_node: class_docstring = docstring_node
                    break
    except Exception as e:
        print(f"Error parsing docstring for {strategy_file}: {e}")

    config_path = get_strategy_config_path(strategy_file)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f: saved_params = json.load(f)
            params.update(saved_params)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading config {config_path}: {e}")

    description_to_use = params.get("description", class_docstring)
    if "description" not in params and description_to_use:
        params["description_from_code"] = description_to_use
    return params, description_to_use, None

def save_strategy_parameters(strategy_file, parameters):
    config_path = get_strategy_config_path(strategy_file)
    try:
        with open(config_path, 'w') as f: json.dump(parameters, f, indent=4)
        return True, "Parameters saved successfully."
    except (IOError, TypeError) as e:
        return False, f"Error saving parameters: {e}"

def get_strategy_stocks_csv_path(strategy_file):
    params, _, _ = get_strategy_parameters(strategy_file)
    default_stocks_csv_name = "stocks.csv"
    stocks_csv_name_from_params = default_stocks_csv_name
    if params and 'stocks_csv_name' in params:
        stocks_csv_name_from_params = params['stocks_csv_name']
    final_csv_name = os.path.basename(stocks_csv_name_from_params)
    return os.path.join(STRATEGY_LIVE_DIR, final_csv_name)

def get_strategy_stocks(strategy_file):
    csv_path = get_strategy_stocks_csv_path(strategy_file)
    stocks = []
    if not os.path.exists(csv_path):
        return stocks, f"Stock file {os.path.basename(csv_path)} not found."
    try:
        with open(csv_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not {'symbol', 'exchange', 'max_fund'}.issubset(reader.fieldnames):
                return [], f"Stock file {os.path.basename(csv_path)} has invalid headers."
            for row in reader:
                row['id'] = f"{row['symbol']}_{row['exchange']}"
                stocks.append(row)
        return stocks, None
    except Exception as e:
        return [], f"Error reading stock file {os.path.basename(csv_path)}: {str(e)}"

def save_strategy_stocks(strategy_file, stocks_data):
    csv_path = get_strategy_stocks_csv_path(strategy_file)
    fieldnames = ['symbol', 'exchange', 'max_fund']
    try:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for stock in stocks_data:
                writer.writerow({field: stock.get(field) for field in fieldnames})
        return True, "Stocks saved successfully."
    except Exception as e:
        return False, f"Error saving stock file {os.path.basename(csv_path)}: {str(e)}"
