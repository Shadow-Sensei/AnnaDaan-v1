from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

# ── Database config ────────────────────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///annadaan.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

db = SQLAlchemy(app)

# ── Models ─────────────────────────────────────────────────────────────────────
class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(10), nullable=False)   # 'donor' | 'ngo'

    # shared profile fields
    org_name     = db.Column(db.String(120))
    contact_name = db.Column(db.String(120))
    phone        = db.Column(db.String(20))
    city         = db.Column(db.String(60))
    state        = db.Column(db.String(60))

    # donor-only
    venue_type   = db.Column(db.String(60))

    # ngo-only
    ngo_reg_number = db.Column(db.String(60))
    capacity       = db.Column(db.Integer)
    area_served    = db.Column(db.String(200))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


# ── Create tables on first run ─────────────────────────────────────────────────
with app.app_context():
    db.create_all()


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data  = request.form
        email = data.get('email', '').strip().lower()
        pw    = data.get('password', '')
        role  = data.get('role', 'donor')

        # ── Validation ──────────────────────────────────
        if not email or not pw:
            return render_template('signup.html', error='Email and password are required.')

        if len(pw) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters.')

        if User.query.filter_by(email=email).first():
            return render_template('signup.html', error='An account with that email already exists.')

        # ── Create user ─────────────────────────────────
        user = User(
            email        = email,
            role         = role,
            org_name     = data.get('org_name', '').strip(),
            contact_name = data.get('contact_name', '').strip(),
            phone        = data.get('phone', '').strip(),
            city         = data.get('city', '').strip(),
            state        = data.get('state', '').strip(),
            venue_type   = data.get('venue_type', '').strip() if role == 'donor' else None,
            ngo_reg_number = data.get('ngo_reg_number', '').strip() if role == 'ngo' else None,
            capacity     = int(data.get('capacity')) if role == 'ngo' and data.get('capacity') else None,
            area_served  = data.get('area_served', '').strip() if role == 'ngo' else None,
        )
        user.set_password(pw)

        db.session.add(user)
        db.session.commit()

        session['user_id']    = user.id
        session['user_email'] = user.email
        session['user_role']  = user.role

        return redirect(url_for('dashboard'))

    # GET → render the signup page
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(pw):
            session['user_id']    = user.id
            session['user_email'] = user.email
            session['user_role']  = user.role
            return redirect(url_for('dashboard'))

        # Invalid credentials → back to login with error
        return render_template('login.html', error='Invalid email or password.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    # Route to role-specific dashboard template
    template = 'donor_dashboard.html' if user.role == 'donor' else 'ngo_dashboard.html'
    return render_template(template, user=user)


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)