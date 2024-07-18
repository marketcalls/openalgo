from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo

class SymbolForm(FlaskForm):
    symbol = StringField('Enter Stock Symbol', validators=[DataRequired()])
    submit = SubmitField('Get Data')

class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request OTP')

class VerifyOTPForm(FlaskForm):
    otp = PasswordField('OTP', validators=[DataRequired()])
    submit = SubmitField('Verify OTP')

class ChangePasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Change Password')

class SymbolForm(FlaskForm):
    symbol = StringField('Enter Stock Symbol', validators=[DataRequired()])
    submit = SubmitField('Get Data')
