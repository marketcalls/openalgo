"""
React Frontend Serving Blueprint
Serves the pre-built React app for all non-API routes.
"""

from pathlib import Path
from flask import Blueprint, send_from_directory, current_app

react_bp = Blueprint('react', __name__)

# Path to the pre-built React frontend
FRONTEND_DIST = Path(__file__).parent.parent / 'frontend' / 'dist'


def is_react_frontend_available():
    """Check if the React frontend build exists."""
    index_html = FRONTEND_DIST / 'index.html'
    return FRONTEND_DIST.exists() and index_html.exists()


@react_bp.route('/', defaults={'path': ''})
@react_bp.route('/<path:path>')
def serve_react(path):
    """
    Serve React app for all frontend routes.
    - Static files (JS, CSS, images) served directly
    - All other routes serve index.html (React Router handles routing)
    """
    if not is_react_frontend_available():
        return """
        <html>
        <head><title>OpenAlgo - Frontend Not Available</title></head>
        <body style="font-family: system-ui; padding: 40px; max-width: 600px; margin: 0 auto;">
            <h1>Frontend Not Built</h1>
            <p>The React frontend is not available. To build it:</p>
            <pre style="background: #f4f4f4; padding: 16px; border-radius: 8px;">
cd frontend
npm install
npm run build</pre>
            <p>Or use the pre-built version from the repository.</p>
            <hr>
            <p><strong>API is still available at:</strong> <code>/api/v1/</code></p>
        </body>
        </html>
        """, 503

    # Try to serve static file first
    file_path = FRONTEND_DIST / path
    if path and file_path.exists() and file_path.is_file():
        return send_from_directory(FRONTEND_DIST, path)

    # Otherwise serve index.html (React Router will handle the route)
    return send_from_directory(FRONTEND_DIST, 'index.html')


@react_bp.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve static assets with long cache headers."""
    assets_dir = FRONTEND_DIST / 'assets'
    if not assets_dir.exists():
        return "Assets not found", 404

    response = send_from_directory(assets_dir, filename)
    # Cache assets for 1 year (they have content hashes in filenames)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
