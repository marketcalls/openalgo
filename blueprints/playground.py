from flask import Blueprint, render_template, request, jsonify, session, current_app
import json
from collections import OrderedDict
import os
import re
import glob
from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

def parse_bru_file(filepath):
    """Parse a Bruno .bru file and extract endpoint information"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        endpoint = {}

        # Extract meta block
        meta_match = re.search(r'meta\s*\{([^}]+)\}', content)
        if meta_match:
            meta_content = meta_match.group(1)
            name_match = re.search(r'name:\s*(.+)', meta_content)
            seq_match = re.search(r'seq:\s*(\d+)', meta_content)
            if name_match:
                endpoint['name'] = name_match.group(1).strip()
            if seq_match:
                endpoint['seq'] = int(seq_match.group(1).strip())

        # Extract HTTP method and URL (post/get/put/delete block)
        method_match = re.search(r'(get|post|put|delete|patch)\s*\{([^}]+)\}', content, re.IGNORECASE)
        if method_match:
            endpoint['method'] = method_match.group(1).upper()
            method_content = method_match.group(2)
            url_match = re.search(r'url:\s*(.+)', method_content)
            if url_match:
                full_url = url_match.group(1).strip()
                # Extract path and query params from URL
                path_match = re.search(r'(/api/v1/[^?]+)', full_url)
                if path_match:
                    endpoint['path'] = path_match.group(1)

                # For GET requests, extract query params from URL
                if endpoint.get('method') == 'GET':
                    query_match = re.search(r'\?(.+)$', full_url)
                    if query_match:
                        query_string = query_match.group(1)
                        params = {}
                        for param in query_string.split('&'):
                            if '=' in param:
                                key, value = param.split('=', 1)
                                # Clear apikey value for security
                                if key == 'apikey':
                                    params[key] = ''
                                else:
                                    params[key] = value
                        if params:
                            endpoint['params'] = params

        # Extract body:json block
        body_match = re.search(r'body:json\s*\{([\s\S]*)\}(?:\s*$|\s*\n)', content)
        if body_match:
            body_content = body_match.group(1).strip()
            try:
                # Use object_pairs_hook to preserve field order from .bru file
                body_json = json.loads(body_content, object_pairs_hook=OrderedDict)
                # Clear the hardcoded API key
                if isinstance(body_json, (dict, OrderedDict)) and 'apikey' in body_json:
                    body_json['apikey'] = ''
                endpoint['body'] = body_json
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON body in {filepath}")

        # Extract query params for GET requests
        params_match = re.search(r'params:query\s*\{([^}]+)\}', content)
        if params_match:
            params = {}
            params_content = params_match.group(1)
            for line in params_content.split('\n'):
                param_match = re.search(r'(\w+):\s*(.+)', line)
                if param_match:
                    key = param_match.group(1).strip()
                    value = param_match.group(2).strip()
                    params[key] = value
            if params:
                endpoint['params'] = params

        return endpoint if 'name' in endpoint and 'path' in endpoint else None

    except Exception as e:
        logger.error(f"Error parsing Bruno file {filepath}: {e}")
        return None

def categorize_endpoint(path):
    """Categorize an endpoint based on its path"""
    path_lower = path.lower()

    # Account endpoints
    if any(x in path_lower for x in ['/funds', '/orderbook', '/tradebook', '/positionbook', '/holdings', '/analyzer', '/margin']):
        return 'account'

    # Order endpoints
    if any(x in path_lower for x in ['/placeorder', '/placesmartorder', '/optionsorder', '/optionsmultiorder',
                                      '/basketorder', '/splitorder', '/modifyorder', '/cancelorder',
                                      '/cancelallorder', '/closeposition', '/orderstatus', '/openposition', '/closeall']):
        return 'orders'

    # Data endpoints
    if any(x in path_lower for x in ['/quotes', '/multiquotes', '/depth', '/history', '/intervals', '/symbol',
                                      '/search', '/expiry', '/optionsymbol', '/optiongreeks', '/optionchain',
                                      '/ticker', '/syntheticfuture', '/instruments']):
        return 'data'

    # Default to utilities
    return 'utilities'

def load_bruno_endpoints():
    """Load all endpoints from Bruno .bru files"""
    endpoints = {
        'account': [],
        'orders': [],
        'data': [],
        'utilities': []
    }

    # Find all .bru files in collections directory
    collections_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'collections')
    bru_files = glob.glob(os.path.join(collections_path, '**', '*.bru'), recursive=True)

    parsed_endpoints = []

    for bru_file in bru_files:
        # Skip collection.bru metadata files
        if os.path.basename(bru_file) == 'collection.bru':
            continue

        endpoint = parse_bru_file(bru_file)
        if endpoint:
            parsed_endpoints.append(endpoint)

    # Sort by sequence number if available
    parsed_endpoints.sort(key=lambda x: x.get('seq', 999))

    # Categorize endpoints
    for endpoint in parsed_endpoints:
        category = categorize_endpoint(endpoint.get('path', ''))
        # Clean up endpoint for frontend (remove seq)
        clean_endpoint = {
            'name': endpoint.get('name', ''),
            'method': endpoint.get('method', 'POST'),
            'path': endpoint.get('path', '')
        }
        if 'body' in endpoint:
            clean_endpoint['body'] = endpoint['body']
        if 'params' in endpoint:
            clean_endpoint['params'] = endpoint['params']

        endpoints[category].append(clean_endpoint)

    # Sort endpoints alphabetically by name within each category
    for category in endpoints:
        endpoints[category].sort(key=lambda x: x.get('name', '').lower())

    return endpoints

playground_bp = Blueprint('playground', __name__, url_prefix='/playground')

@playground_bp.route('/')
@check_session_validity
def index():
    """Render the API tester page"""
    login_username = session.get('user')
    # Get the decrypted API key if it exists
    api_key = get_api_key_for_tradingview(login_username) if login_username else None
    logger.info(f"Playground accessed by user: {login_username}")
    return render_template('playground.html', 
                         login_username=login_username,
                         api_key=api_key or '')

@playground_bp.route('/api-key')
@check_session_validity
def get_api_key():
    """Get the current user's API key"""
    login_username = session.get('user')
    if not login_username:
        return jsonify({'error': 'Not authenticated'}), 401
    
    api_key = get_api_key_for_tradingview(login_username)
    return jsonify({'api_key': api_key or ''})

@playground_bp.route('/collections')
@check_session_validity
def get_collections():
    """Get all available API collections"""
    collections = []
    
    # Load Postman collection
    postman_path = os.path.join('collections', 'postman', 'openalgo.postman_collection.json')
    if os.path.exists(postman_path):
        with open(postman_path, 'r') as f:
            postman_data = json.load(f)
            collections.append({
                'name': 'Postman Collection',
                'type': 'postman',
                'data': postman_data
            })
    
    # Load Bruno collection
    bruno_path = os.path.join('collections', 'openalgo_bruno.json')
    if os.path.exists(bruno_path):
        with open(bruno_path, 'r') as f:
            bruno_data = json.load(f)
            collections.append({
                'name': 'Bruno Collection',
                'type': 'bruno',
                'data': bruno_data
            })
    
    return jsonify(collections)

@playground_bp.route('/endpoints')
@check_session_validity
def get_endpoints():
    """Get structured list of all API endpoints from Bruno collections"""
    try:
        endpoints = load_bruno_endpoints()

        # If no endpoints loaded from Bruno, return empty structure
        if not any(endpoints.values()):
            logger.warning("No endpoints loaded from Bruno collections")
            return current_app.response_class(
                response=json.dumps({
                    'account': [],
                    'orders': [],
                    'data': [],
                    'utilities': []
                }),
                status=200,
                mimetype='application/json'
            )

        logger.info(f"Loaded {sum(len(v) for v in endpoints.values())} endpoints from Bruno collections")
        # Return with sort_keys=False to preserve field order from .bru files
        return current_app.response_class(
            response=json.dumps(endpoints, sort_keys=False),
            status=200,
            mimetype='application/json'
        )

    except Exception as e:
        logger.error(f"Error loading endpoints: {e}")
        return jsonify({'error': 'Failed to load endpoints'}), 500
