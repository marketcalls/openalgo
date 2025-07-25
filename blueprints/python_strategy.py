# blueprints/python_strategy.py
from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
import os
import glob
from utils.python_strategy_manager import (
    get_all_strategy_statuses, activate_strategy, deactivate_strategy,
    get_strategy_files, get_strategy_parameters, save_strategy_parameters,
    get_strategy_stocks, save_strategy_stocks, get_strategy_stocks_csv_path,
    read_strategy_log # Add this import
)
from werkzeug.utils import secure_filename # For strategy_filename
from utils.session import check_session_validity, is_session_valid

python_strategy_bp = Blueprint(
    'python_strategy_bp', __name__,
    template_folder='../templates/python_strategy',
    static_folder='../static',
    url_prefix='/python_strategy'
)

@python_strategy_bp.route('/')
@check_session_validity
def index():
    statuses = get_all_strategy_statuses()
    all_files = get_strategy_files()
    current_strategies_on_page = []

    for f_name in all_files:
        status_info = statuses.get(f_name, {'status': 'inactive', 'pid': None})

        # Fetch parameters and description for this strategy
        # We only need the description here, but get_strategy_parameters gets both params and desc.
        # If this becomes a performance issue for many strategies, a dedicated get_description func could be made.
        _, strategy_description, _ = get_strategy_parameters(f_name) # params, desc, error_msg

        current_strategies_on_page.append({
            'name': f_name.replace('_live.py', '').replace('_', ' ').title(),
            'file_name': f_name,
            'status': status_info.get('status', 'inactive'),
            'pid': status_info.get('pid'),
            'description': strategy_description if strategy_description else "No description available." # Add description
        })

    if not current_strategies_on_page: # Simplified condition as all_files would be empty too
        flash("No Python strategy files found in the 'strategy_live' folder or the folder is missing.", "info")

    return render_template('py_strat_index.html', strategies=current_strategies_on_page)

@python_strategy_bp.route('/activate/<strategy_filename>', methods=['POST'])
@check_session_validity
def activate(strategy_filename):
    # Add security checks here if needed (e.g., user authentication/authorization)
    # For example, ensure the user has permission to manage strategies.
    # from flask_login import current_user, login_required
    # if not current_user.is_authenticated or not current_user.has_role('admin'):
    #     flash("You are not authorized to perform this action.", "error")
    #     return redirect(url_for('python_strategy_bp.index'))

    success, message = activate_strategy(strategy_filename)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('python_strategy_bp.index'))


@python_strategy_bp.route('/logs/<strategy_filename>')
@check_session_validity
def view_strategy_log(strategy_filename):
    # Sanitize filename (though it's from our system, good practice if ever linked from user input)
    # However, strategy_filename here comes from a list of files on the server,
    # so direct secure_filename might be too aggressive if filenames can have unusual but valid chars.
    # For now, assume strategy_filename is safe as it's derived from os.listdir/glob.

    # Use a reasonable number of lines to display by default to avoid browser slowdown for huge logs
    # This can be made configurable later if needed.
    log_content = read_strategy_log(strategy_filename, tail_lines=500)

    strategy_name_display = strategy_filename.replace('_live.py', '').replace('.py', '').replace('_', ' ').title()

    return render_template(
        'view_log.html',
        strategy_name=strategy_name_display,
        log_content=log_content,
        strategy_filename=strategy_filename # Pass original filename for potential refresh/back links
    )


@python_strategy_bp.route('/details/<strategy_filename>/stock/add', methods=['POST'])
@check_session_validity
def add_stock(strategy_filename):
    strategy_filename = secure_filename(strategy_filename) # Basic security
    # Add user authentication/authorization checks if necessary

    symbol = request.form.get('symbol', '').upper()
    exchange = request.form.get('exchange', '').upper()
    max_fund_str = request.form.get('max_fund', '0')

    if not symbol or not exchange:
        flash('Symbol and Exchange are required.', 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    try:
        max_fund = int(max_fund_str)
        if max_fund < 0:
            flash('Max Fund cannot be negative.', 'error')
            return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))
    except ValueError:
        flash('Max Fund must be a valid number.', 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    stocks, error_msg = get_strategy_stocks(strategy_filename)
    if error_msg and not stocks: # If error and no stocks, might be an issue reading.
         # flash(f"Could not load existing stocks to add: {error_msg}", "warning")
         # Allow adding even if file didn't exist or was empty. `stocks` will be []
         pass


    # Check for duplicates
    # The stocks list here is already strategy-specific due to changes in get_strategy_stocks
    if any(s['symbol'] == symbol and s['exchange'] == exchange for s in stocks):
        flash(f"Stock {symbol} on {exchange} already exists for this strategy.", 'error') # Clarified message
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    # Derive strategy_id from strategy_filename
    current_strategy_key = strategy_filename.replace('_live.py', '').replace('.py', '')

    new_stock_entry = {
        'symbol': symbol,
        'exchange': exchange,
        'max_fund': max_fund,
        'strategy_id': current_strategy_key  # Add strategy_id
    }
    stocks.append(new_stock_entry)

    # Now, `stocks` contains the full list for the current strategy, including the new one with its strategy_id
    # `save_strategy_stocks` will handle merging this with other strategies' stocks in the CSV
    success, save_message = save_strategy_stocks(strategy_filename, stocks)
    if success:
        flash(f"Stock {symbol} added successfully.", 'success')
    else:
        flash(f"Error adding stock {symbol}: {save_message}", 'error')

    return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

@python_strategy_bp.route('/details/<strategy_filename>/stock/edit/<stock_id>', methods=['POST'])
@check_session_validity
def edit_stock(strategy_filename, stock_id):
    strategy_filename = secure_filename(strategy_filename)
    # stock_id is expected to be 'SYMBOL_EXCHANGE'

    new_symbol = request.form.get('symbol', '').upper()
    new_exchange = request.form.get('exchange', '').upper()
    new_max_fund_str = request.form.get('max_fund', '0')

    if not new_symbol or not new_exchange:
        flash('Symbol and Exchange are required for editing.', 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    try:
        new_max_fund = int(new_max_fund_str)
        if new_max_fund < 0:
            flash('Max Fund cannot be negative.', 'error')
            return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))
    except ValueError:
        flash('Max Fund must be a valid number for editing.', 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    stocks, error_msg = get_strategy_stocks(strategy_filename)
    if error_msg and not stocks:
        flash(f"Could not load stocks to edit: {error_msg}", 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    stock_found = False
    updated_stocks = []
    # Derive strategy_id from strategy_filename to be used for the edited entry
    current_strategy_key = strategy_filename.replace('_live.py', '').replace('.py', '')

    for i, stock_from_get in enumerate(stocks): # stock_from_get should have strategy_id if from new get_strategy_stocks
        current_stock_ui_id = f"{stock_from_get.get('symbol')}_{stock_from_get.get('exchange')}" # Use .get for safety
        if current_stock_ui_id == stock_id: # stock_id is the ID of the stock being edited
            stock_found = True
            # Check if the new symbol/exchange combination conflicts with another existing stock IN THIS STRATEGY'S LIST
            if (new_symbol != stock_from_get.get('symbol') or new_exchange != stock_from_get.get('exchange')) and \
               any(s.get('symbol') == new_symbol and s.get('exchange') == new_exchange for idx, s in enumerate(stocks) if idx != i):
                flash(f"Another stock with symbol {new_symbol} on {new_exchange} already exists for this strategy. Cannot update.", 'error') # Clarified
                return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

            updated_stocks.append({
                'symbol': new_symbol,
                'exchange': new_exchange,
                'max_fund': new_max_fund,
                'strategy_id': current_strategy_key  # Add/Ensure correct strategy_id for the edited stock
            })
        else:
            # For other stocks not being edited, append them as they are.
            # They should already have their correct strategy_id from get_strategy_stocks.
            updated_stocks.append(stock_from_get)

    if not stock_found:
        flash(f"Stock with ID {stock_id} not found for editing.", 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    success, save_message = save_strategy_stocks(strategy_filename, updated_stocks)
    if success:
        flash(f"Stock {stock_id} updated successfully to {new_symbol}.", 'success')
    else:
        flash(f"Error updating stock {stock_id}: {save_message}", 'error')

    return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))


@python_strategy_bp.route('/details/<strategy_filename>/stock/delete/<stock_id>', methods=['POST'])
@check_session_validity
def delete_stock(strategy_filename, stock_id):
    strategy_filename = secure_filename(strategy_filename)
    # stock_id is 'SYMBOL_EXCHANGE'

    stocks, error_msg = get_strategy_stocks(strategy_filename)
    if error_msg and not stocks: # If error and no stocks, nothing to delete or error reading
        flash(f"Could not load stocks to delete: {error_msg}", 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    original_len = len(stocks)
    # The stock_id in get_strategy_stocks is s['id'] = f"{row['symbol']}_{row['exchange']}"
    stocks_after_deletion = [s for s in stocks if s.get('id') != stock_id]

    if len(stocks_after_deletion) == original_len:
        flash(f"Stock with ID {stock_id} not found for deletion.", 'warning')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    success, save_message = save_strategy_stocks(strategy_filename, stocks_after_deletion)
    if success:
        flash(f"Stock {stock_id} deleted successfully.", 'success')
    else:
        flash(f"Error deleting stock {stock_id}: {save_message}", 'error')

    return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))


@python_strategy_bp.route('/details/<strategy_filename>', methods=['GET', 'POST'])
@check_session_validity
def details(strategy_filename):
    strategy_name_display = strategy_filename.replace('_live.py', '').replace('_', ' ').title()

    if request.method == 'POST':
        updated_params = {}
        raw_form_params = request.form.to_dict()

        # Load current params to know their types for proper conversion and to preserve ones not in form
        current_params, _, _ = get_strategy_parameters(strategy_filename)
        if current_params is None: current_params = {} # Should not happen if file exists

        # Iterate over current_params to ensure all existing keys are considered,
        # and update them from form if present.
        # This also helps preserve parameters that might not be editable via this specific form.
        for key in current_params.keys():
            if key == 'description_from_code': # This is not a saved param
                continue

            if key in raw_form_params:
                value = raw_form_params[key]
                original_value = current_params.get(key) # Get type from original loaded params

                if isinstance(original_value, bool):
                    if value.lower() == 'true': updated_params[key] = True
                    elif value.lower() == 'false': updated_params[key] = False
                    else: updated_params[key] = value # Or some error/default
                elif isinstance(original_value, int):
                    try: updated_params[key] = int(value)
                    except ValueError: updated_params[key] = original_value # Revert to original if conversion fails
                elif isinstance(original_value, float):
                    try: updated_params[key] = float(value)
                    except ValueError: updated_params[key] = original_value # Revert
                else: # Default to string, or handle other types if necessary
                    updated_params[key] = value
            elif isinstance(current_params.get(key), bool):
                # Handle checkboxes/boolean selects not present in form data (means false)
                 updated_params[key] = False
            else:
                # If key from current_params is not in form, retain its original value
                # This is important for params not included in this specific form.
                # However, all editable params SHOULD be in the form.
                # This case might apply if we have multiple forms editing subsets of params.
                # For a single comprehensive param form, all keys should be in raw_form_params.
                # For safety, let's assume if it's not in form, it wasn't meant to be changed by this form.
                updated_params[key] = current_params.get(key)


        # If 'description' was specifically edited (e.g. via a textarea) and is in raw_form_params
        if 'description' in raw_form_params:
             updated_params['description'] = raw_form_params['description']


        # Remove 'description_from_code' if it accidentally got into updated_params
        if 'description_from_code' in updated_params:
            del updated_params['description_from_code']

        success, message = save_strategy_parameters(strategy_filename, updated_params)
        if success: flash(f"Parameters for {strategy_name_display} saved successfully.", 'success')
        else: flash(f"Error saving parameters for {strategy_name_display}: {message}", 'error')
        return redirect(url_for('python_strategy_bp.details', strategy_filename=strategy_filename))

    # GET request: Display parameters, description, and stocks
    params, strategy_description, error_msg_params = get_strategy_parameters(strategy_filename) # Unpack description

    if error_msg_params:
        flash(error_msg_params, 'error')
        return redirect(url_for('python_strategy_bp.index'))

    if params is None: params = {}
    # 'description_from_code' is already handled by get_strategy_parameters and put into params if needed.
    # 'strategy_description' holds the final description to display (either from param['description'] or docstring).

    stocks, error_msg_stocks = get_strategy_stocks(strategy_filename)
    if error_msg_stocks and not stocks:
         flash(f"Note on stocks for {strategy_name_display}: {error_msg_stocks}", 'warning')

    stocks_csv_path_display = os.path.basename(get_strategy_stocks_csv_path(strategy_filename))

    return render_template(
        'details.html',
        strategy_name=strategy_name_display,
        strategy_filename=strategy_filename,
        parameters=params,
        strategy_description=strategy_description,
        stocks=stocks,
        stocks_csv_path_display=stocks_csv_path_display
    )

@python_strategy_bp.route('/deactivate/<strategy_filename>', methods=['POST'])
@check_session_validity
def deactivate(strategy_filename):
    # Similar security checks as in activate route
    # from flask_login import current_user, login_required  # Example
    # if not current_user.is_authenticated or not current_user.has_role('admin'): # Example
    #     flash("You are not authorized to perform this action.", "error") # Example
    #     return redirect(url_for('python_strategy_bp.index')) # Example

    success, message = deactivate_strategy(strategy_filename)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('python_strategy_bp.index'))
