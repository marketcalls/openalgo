from flask import Blueprint, current_app, send_from_directory ,render_template
import os

core_bp = Blueprint('core_bp', __name__)

@core_bp.route('/')
def home():
    return render_template('index.html')

@core_bp.route('/docs/')
def docs():
    docs_dir = os.path.join(current_app.root_path, 'docs')
    return send_from_directory(docs_dir, 'index.html')

@core_bp.route('/docs/<path:filename>')
def docs_file(filename):
    docs_dir = os.path.join(current_app.root_path, 'docs')
    return send_from_directory(docs_dir, filename)
