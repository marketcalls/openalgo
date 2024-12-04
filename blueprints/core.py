from flask import Blueprint, render_template, redirect, request, url_for, session, flash
from database.user_db import add_user, find_user_by_username
from utils.session import invalidate_session_if_invalid
import logging
import qrcode
import io
import base64

logger = logging.getLogger(__name__)

core_bp = Blueprint('core_bp', __name__)

@core_bp.route('/')
@invalidate_session_if_invalid
def home():
    return render_template('index.html')

@core_bp.route('/download')
@invalidate_session_if_invalid
def download():
    return render_template('download.html')

@core_bp.route('/faq')
@invalidate_session_if_invalid
def faq():
    return render_template('faq.html')

@core_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if find_user_by_username() is not None:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # Add the new admin user
        user = add_user(username, email, password, is_admin=True)
        if user:
            logger.info(f"New admin user {username} created successfully")
            
            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(user.get_totp_uri())
            qr.make(fit=True)
            
            # Create QR code image
            img_buffer = io.BytesIO()
            qr.make_image(fill_color="black", back_color="white").save(img_buffer, format='PNG')
            qr_code = base64.b64encode(img_buffer.getvalue()).decode()
            
            # Store TOTP setup in session temporarily
            session['totp_setup'] = True
            session['username'] = username
            
            return render_template('totp_setup.html', 
                                 qr_code=qr_code,
                                 secret=user.totp_secret)
        else:
            # If the user already exists or an error occurred, show an error message
            logger.error(f"Failed to create admin user {username}")
            flash('User already exists or an error occurred', 'error')
            return redirect(url_for('core_bp.setup'))
            
    return render_template('setup.html')
