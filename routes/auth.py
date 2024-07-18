from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, mail, bcrypt
from forms import RegistrationForm, LoginForm, ForgotPasswordForm, VerifyOTPForm, ChangePasswordForm
from models import User
from flask_mail import Message
import random

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        new_user = User(email=form.email.data, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        send_welcome_email(new_user.email)
        flash('User Registered Successfully', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user)
            flash('Login Successful', 'success')
            return redirect(url_for('dashboard.dashboard'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            otp = generate_otp()
            user.otp = otp
            db.session.commit()
            send_otp_email(user.email, otp)
            flash('OTP sent to your email', 'info')
            return redirect(url_for('auth.verify_otp'))
        else:
            flash('Email not found', 'danger')
    return render_template('forgot_password.html', form=form)

@auth_bp.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    form = VerifyOTPForm()
    if form.validate_on_submit():
        user = User.query.filter_by(otp=form.otp.data).first()
        if user:
            flash('OTP verified successfully', 'success')
            return redirect(url_for('auth.change_password', otp=form.otp.data))
        else:
            flash('Invalid OTP', 'danger')
    return render_template('verify_otp.html', form=form)

@auth_bp.route('/change_password/<otp>', methods=['GET', 'POST'])
def change_password(otp):
    form = ChangePasswordForm()
    user = User.query.filter_by(otp=otp).first()
    if not user:
        flash('Invalid or expired OTP', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if form.validate_on_submit():
        user.password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.otp = None
        db.session.commit()
        flash('Password changed successfully', 'success')
        return redirect(url_for('auth.login'))
    return render_template('change_password.html', form=form)

def generate_otp():
    return ''.join(random.choices('0123456789', k=6))

def send_welcome_email(to):
    msg = Message('Welcome to OpenDash', recipients=[to])
    msg.html = render_template('email/welcome.html')
    mail.send(msg)

def send_otp_email(to, otp):
    msg = Message('Your OTP Code', recipients=[to])
    msg.body = f'Your OTP code is {otp}'
    mail.send(msg)
