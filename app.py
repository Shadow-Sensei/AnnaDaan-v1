from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, math

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///annadaan.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE']   = False          # set True when serving over HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['GOOGLE_MAPS_KEY'] = 'AIzaSyCe3iJpvCdND7hQ949oCwqLadTO5ynzaG4'

db = SQLAlchemy(app)

# ── Models ─────────────────────────────────────────────────────────────────────

class User(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    email          = db.Column(db.String(120), unique=True, nullable=False)
    password_hash  = db.Column(db.String(256), nullable=False)
    role           = db.Column(db.String(10), nullable=False)   # 'donor' | 'ngo'
    org_name       = db.Column(db.String(120))
    contact_name   = db.Column(db.String(120))
    phone          = db.Column(db.String(20))
    city           = db.Column(db.String(60))
    state          = db.Column(db.String(60))
    venue_type     = db.Column(db.String(60))
    ngo_reg_number = db.Column(db.String(60))
    capacity       = db.Column(db.Integer)
    area_served    = db.Column(db.String(200))
    lat            = db.Column(db.Float, nullable=True)
    lng            = db.Column(db.Float, nullable=True)
    listings       = db.relationship('Listing', backref='donor', lazy=True, foreign_keys='Listing.donor_id')

    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

    def to_profile_dict(self):
        return {
            'id':             self.id,
            'email':          self.email,
            'role':           self.role,
            'org_name':       self.org_name       or '',
            'contact_name':   self.contact_name   or '',
            'phone':          self.phone           or '',
            'city':           self.city            or '',
            'state':          self.state           or '',
            'venue_type':     self.venue_type      or '',
            'ngo_reg_number': self.ngo_reg_number  or '',
            'capacity':       self.capacity        or '',
            'area_served':    self.area_served     or '',
            'lat':            self.lat,
            'lng':            self.lng,
        }


class Listing(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    donor_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    food_name    = db.Column(db.String(200), nullable=False)
    quantity     = db.Column(db.Integer, nullable=False)
    food_type    = db.Column(db.String(80))
    pickup_by    = db.Column(db.String(40))          # stored as ISO string
    contact      = db.Column(db.String(30))
    notes        = db.Column(db.Text)
    city         = db.Column(db.String(60))
    status       = db.Column(db.String(20), default='available')  # available | claimed | expired
    claimed_by   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimed_at   = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    lat          = db.Column(db.Float, nullable=True)
    lng          = db.Column(db.Float, nullable=True)

    claimer      = db.relationship('User', foreign_keys=[claimed_by], backref='claims')

    def to_dict(self, current_user_id=None, ngo_lat=None, ngo_lng=None):
        donor = User.query.get(self.donor_id)
        claimer = User.query.get(self.claimed_by) if self.claimed_by else None
        distance_km = None
        if ngo_lat and ngo_lng and self.lat and self.lng:
            distance_km = _haversine(ngo_lat, ngo_lng, self.lat, self.lng)
        return {
            'id':          self.id,
            'food_name':   self.food_name,
            'quantity':    self.quantity,
            'food_type':   self.food_type or 'Cooked food',
            'pickup_by':   self.pickup_by or '',
            'contact':     self.contact or '',
            'notes':       self.notes or '',
            'city':        self.city or '',
            'status':      self.status,
            'created_at':  self.created_at.strftime('%d %b %Y, %I:%M %p'),
            'donor_name':  donor.org_name or donor.contact_name or 'Donor',
            'donor_phone': self.contact or donor.phone or '',
            'claimed_by_name': claimer.org_name or claimer.contact_name if claimer else None,
            'claimed_by_phone': claimer.phone if claimer else None,
            'is_mine':     (self.donor_id == current_user_id),
            'lat':         self.lat,
            'lng':         self.lng,
            'distance_km': round(distance_km, 1) if distance_km is not None else None,
        }


with app.app_context():
    db.create_all()


# ── Geo helpers ────────────────────────────────────────────────────────────────

def _haversine(lat1, lon1, lat2, lon2):
    """Return distance in km between two lat/lng points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ── Session helper ─────────────────────────────────────────────────────────────

def _create_session(user):
    """Create a permanent (remembered) session — stays alive for 30 days."""
    session.permanent     = True
    session['user_id']    = user.id
    session['user_email'] = user.email
    session['user_role']  = user.role


# ── Auth helpers ───────────────────────────────────────────────────────────────

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(role=None):
    """Returns (user, error_redirect)"""
    user = current_user()
    if not user:
        return None, redirect(url_for('login'))
    if role and user.role != role:
        return None, redirect(url_for('dashboard'))
    return user, None


# ── Page Routes ────────────────────────────────────────────────────────────────

@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/')
def index():
    stats = {
        'meals':  db.session.query(db.func.sum(Listing.quantity)).filter_by(status='claimed').scalar() or 0,
        'ngos':   User.query.filter_by(role='ngo').count(),
        'cities': db.session.query(db.func.count(db.func.distinct(User.city))).scalar() or 0,
    }
    return render_template('index.html', stats=stats)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        print("=== SIGNUP POST ===", dict(request.form))
        data  = request.form
        email = data.get('email', '').strip().lower()
        pw    = data.get('password', '')
        role  = data.get('role', 'donor')

        if not email or not pw:
            return render_template('signup.html', error='Email and password are required.')
        if len(pw) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters.')
        if User.query.filter_by(email=email).first():
            return render_template('signup.html', error='An account with that email already exists.')

        user = User(
            email          = email,
            role           = role,
            org_name       = data.get('org_name', '').strip(),
            contact_name   = data.get('contact_name', '').strip(),
            phone          = data.get('phone', '').strip(),
            city           = data.get('city', '').strip(),
            state          = data.get('state', '').strip(),
            venue_type     = data.get('venue_type', '').strip() if role == 'donor' else None,
            ngo_reg_number = data.get('ngo_reg_number', '').strip() if role == 'ngo' else None,
            capacity       = int(data.get('capacity')) if role == 'ngo' and data.get('capacity') else None,
            area_served    = data.get('area_served', '').strip() if role == 'ngo' else None,
            lat            = float(data.get('lat')) if data.get('lat') else None,
            lng            = float(data.get('lng')) if data.get('lng') else None,
        )
        user.set_password(pw)
        db.session.add(user)
        db.session.commit()

        _create_session(user)
        return redirect(url_for('dashboard'))

    return render_template('signup.html', maps_key=app.config['GOOGLE_MAPS_KEY'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        user  = User.query.filter_by(email=email).first()
        if user and user.check_password(pw):
            _create_session(user)
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid email or password.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/dashboard')
def dashboard():
    user, err = login_required()
    if err: return err
    template = 'donor_dashboard.html' if user.role == 'donor' else 'ngo_dashboard.html'
    return render_template(template, user=user)


@app.route('/profile')
def profile():
    user, err = login_required()
    if err: return err
    return render_template('profile.html', user=user)


# ── API: Profile ───────────────────────────────────────────────────────────────

@app.route('/api/profile', methods=['GET'])
def get_profile():
    user, err = login_required()
    if err: return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'user': user.to_profile_dict()})


@app.route('/api/profile', methods=['PATCH'])
def update_profile():
    user, err = login_required()
    if err: return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided.'}), 400

    allowed = ['org_name', 'contact_name', 'phone', 'city', 'state']
    if user.role == 'donor':
        allowed.append('venue_type')
    else:
        allowed += ['ngo_reg_number', 'area_served']

    for field in allowed:
        if field in data:
            setattr(user, field, data[field].strip() if isinstance(data[field], str) else data[field])

    if user.role == 'ngo' and 'capacity' in data:
        try:
            user.capacity = int(data['capacity']) if data['capacity'] else None
        except (ValueError, TypeError):
            pass

    db.session.commit()
    return jsonify({'success': True, 'user': user.to_profile_dict()})


@app.route('/api/profile/location', methods=['PATCH'])
def update_location():
    user, err = login_required()
    if err: return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    try:
        user.lat  = float(data.get('lat'))
        user.lng  = float(data.get('lng'))
        user.city = data.get('city', user.city or '').strip()
        db.session.commit()
        return jsonify({'success': True, 'lat': user.lat, 'lng': user.lng})
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid coordinates'}), 400


@app.route('/api/profile/password', methods=['POST'])
def change_password():
    user, err = login_required()
    if err: return jsonify({'error': 'Unauthorized'}), 401

    data       = request.get_json()
    current_pw = data.get('current_password', '')
    new_pw     = data.get('new_password', '')

    if not user.check_password(current_pw):
        return jsonify({'error': 'Current password is incorrect.'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': 'New password must be at least 8 characters.'}), 400

    user.set_password(new_pw)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/profile', methods=['DELETE'])
def delete_account():
    user, err = login_required()
    if err: return jsonify({'error': 'Unauthorized'}), 401

    # Unclaim any NGO claims so listings go back to available
    Listing.query.filter_by(claimed_by=user.id).update(
        {'claimed_by': None, 'claimed_at': None, 'status': 'available'}
    )
    # Delete donor's own listings
    Listing.query.filter_by(donor_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    session.clear()
    return jsonify({'success': True})


# ── API: Listings (Donor) ──────────────────────────────────────────────────────

@app.route('/api/listings', methods=['POST'])
def post_listing():
    user, err = login_required(role='donor')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or not data.get('food_name') or not data.get('quantity'):
        return jsonify({'error': 'Food name and quantity are required.'}), 400

    listing = Listing(
        donor_id  = user.id,
        food_name = data['food_name'].strip(),
        quantity  = int(data['quantity']),
        food_type = data.get('food_type', ''),
        pickup_by = data.get('pickup_by', ''),
        contact   = data.get('contact', user.phone or ''),
        notes     = data.get('notes', ''),
        city      = user.city or '',
        lat       = user.lat,
        lng       = user.lng,
    )
    db.session.add(listing)
    db.session.commit()
    return jsonify({'success': True, 'listing': listing.to_dict(user.id)}), 201


@app.route('/api/listings/mine', methods=['GET'])
def my_listings():
    user, err = login_required(role='donor')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listings = Listing.query.filter_by(donor_id=user.id).order_by(Listing.created_at.desc()).all()
    return jsonify({'listings': [l.to_dict(user.id) for l in listings]})


@app.route('/api/listings/donor-stats', methods=['GET'])
def donor_stats():
    user, err = login_required(role='donor')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    total    = Listing.query.filter_by(donor_id=user.id).count()
    claimed  = Listing.query.filter_by(donor_id=user.id, status='claimed').count()
    meals    = db.session.query(db.func.sum(Listing.quantity))\
                 .filter_by(donor_id=user.id, status='claimed').scalar() or 0
    ngos     = db.session.query(db.func.count(db.func.distinct(Listing.claimed_by)))\
                 .filter(Listing.donor_id==user.id, Listing.claimed_by != None).scalar() or 0
    return jsonify({'total': total, 'claimed': claimed, 'meals': meals, 'ngos': ngos})


# ── API: Feed + Claims (NGO) ───────────────────────────────────────────────────

@app.route('/api/feed', methods=['GET'])
def ngo_feed():
    user, err = login_required(role='ngo')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listings = Listing.query.filter_by(status='available').limit(50).all()

    ngo_lat, ngo_lng = user.lat, user.lng

    if ngo_lat and ngo_lng:
        # Sort by distance ascending; listings without coords go to end
        def sort_key(l):
            if l.lat and l.lng:
                return _haversine(ngo_lat, ngo_lng, l.lat, l.lng)
            return 9999
        listings.sort(key=sort_key)
    else:
        # Fallback: same city first
        listings.sort(key=lambda l: (0 if l.city == user.city else 1))

    return jsonify({
        'listings': [l.to_dict(user.id, ngo_lat, ngo_lng) for l in listings],
        'ngo_lat': ngo_lat,
        'ngo_lng': ngo_lng,
    })


@app.route('/api/listings/<int:listing_id>/claim', methods=['POST'])
def claim_listing(listing_id):
    user, err = login_required(role='ngo')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listing = Listing.query.get_or_404(listing_id)
    if listing.status != 'available':
        return jsonify({'error': 'This listing has already been claimed.'}), 409

    listing.status     = 'claimed'
    listing.claimed_by = user.id
    listing.claimed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'listing': listing.to_dict(user.id)})


@app.route('/api/listings/claimed', methods=['GET'])
def ngo_claimed():
    user, err = login_required(role='ngo')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listings = Listing.query.filter_by(claimed_by=user.id)\
                 .order_by(Listing.claimed_at.desc()).all()
    return jsonify({'listings': [l.to_dict(user.id) for l in listings]})


@app.route('/api/listings/ngo-stats', methods=['GET'])
def ngo_stats():
    user, err = login_required(role='ngo')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    claimed = Listing.query.filter_by(claimed_by=user.id).count()
    meals   = db.session.query(db.func.sum(Listing.quantity))\
                .filter_by(claimed_by=user.id).scalar() or 0
    donors  = db.session.query(db.func.count(db.func.distinct(Listing.donor_id)))\
                .filter(Listing.claimed_by==user.id).scalar() or 0
    return jsonify({'claimed': claimed, 'meals': meals, 'donors': donors})


@app.route('/api/listings/<int:listing_id>', methods=['DELETE'])
def delete_listing(listing_id):
    user, err = login_required(role='donor')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listing = Listing.query.get_or_404(listing_id)
    if listing.donor_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    if listing.status == 'claimed':
        return jsonify({'error': 'Cannot delete a claimed listing.'}), 409

    db.session.delete(listing)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/listings/<int:listing_id>', methods=['PATCH'])
def edit_listing(listing_id):
    user, err = login_required(role='donor')
    if err: return jsonify({'error': 'Unauthorized'}), 401

    listing = Listing.query.get_or_404(listing_id)
    if listing.donor_id != user.id:
        return jsonify({'error': 'Forbidden'}), 403
    if listing.status == 'claimed':
        return jsonify({'error': 'Cannot edit a claimed listing.'}), 409

    data = request.get_json()
    if data.get('food_name'):  listing.food_name = data['food_name'].strip()
    if data.get('quantity'):   listing.quantity  = int(data['quantity'])
    if 'food_type' in data:    listing.food_type = data['food_type']
    if 'pickup_by' in data:    listing.pickup_by = data['pickup_by']
    if 'contact'   in data:    listing.contact   = data['contact']
    if 'notes'     in data:    listing.notes     = data['notes']

    db.session.commit()
    return jsonify({'success': True, 'listing': listing.to_dict(user.id)})



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)