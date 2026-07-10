import os
import datetime
import random
import psutil
import requests
import pycountry
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
import threading
import time
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from functools import wraps
from google import genai
from google.genai import types
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from twilio.twiml.messaging_response import MessagingResponse

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cryptography.fernet import Fernet

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret")
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vela.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10000 per day", "10000 per hour"],
    storage_uri="memory://"
)

socketio = SocketIO(app, cors_allowed_origins="*")

fernet_key_env = os.getenv("FERNET_KEY")
if not fernet_key_env:
    fernet_key_env = Fernet.generate_key().decode()
fernet = Fernet(fernet_key_env.encode())

# --- DATABASE MODELS ---

class BannedIP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(100), unique=True)
    reason = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.String(6), unique=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    phone_number = db.Column(db.String(50))
    password_hash = db.Column(db.String(255))
    country = db.Column(db.String(100))
    profile_image = db.Column(db.String(255))
    
    occupation = db.Column(db.String(100))
    age_group = db.Column(db.String(50))
    goals = db.Column(db.String(255))
    onboarding_completed = db.Column(db.Boolean, default=False)

    ip_address = db.Column(db.String(100))
    registration_date = db.Column(db.DateTime, default=datetime.datetime.now)
    last_login = db.Column(db.DateTime)
    
    # Phase 10 Gamification & Personality
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    current_streak = db.Column(db.Integer, default=0)
    ai_personality = db.Column(db.String(50), default='Professional Assistant')

    # Phase 10 Trust Layer
    allow_ai_calendar = db.Column(db.Boolean, default=True)
    allow_ai_finances = db.Column(db.Boolean, default=True)
    
    # Phase 11 Multi-Language
    preferred_language = db.Column(db.String(20), default='en')
    
    # Phase 3 Autonomous Communication
    read_notifications_aloud = db.Column(db.Boolean, default=True)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(100))
    ip_address = db.Column(db.String(100))
    location_data = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class PlaidItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    encrypted_access_token = db.Column(db.LargeBinary)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    role = db.Column(db.String(50)) 
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class VerificationCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100))
    phone_number = db.Column(db.String(50))
    code = db.Column(db.String(10))
    expires_at = db.Column(db.DateTime)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    date = db.Column(db.Date)
    time = db.Column(db.Time)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

class HealthLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.Date)
    weight_lbs = db.Column(db.Float)
    calories = db.Column(db.Integer)
    water_glasses = db.Column(db.Integer)
    workout_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

class Routine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    task_name = db.Column(db.String(255))
    frequency = db.Column(db.String(50)) # e.g. "Daily"
    last_completed = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

ai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
configuration = plaid.Configuration(
    host=plaid.Environment.Sandbox,
    api_key={'clientId': os.getenv('PLAID_CLIENT_ID'), 'secret': os.getenv('PLAID_SECRET')}
)
plaid_client = plaid_api.PlaidApi(plaid.ApiClient(configuration))

# --- GLOBAL CONFIG ---
GLOBAL_LOCKDOWN = False

# --- WEBSOCKETS ---
def admin_live_feed():
    """Background task to push live physical server stats to the 'admin' room."""
    with app.app_context():
        while True:
            time.sleep(3)
            try:
                # Real physical server metrics
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory()
                net_io = psutil.net_io_counters()
                
                # Convert bytes to MB for display
                net_mb = round((net_io.bytes_sent + net_io.bytes_recv) / (1024 * 1024), 2)
                
                alerts = [
                    f"[SYS] Real CPU usage at {cpu}%...",
                    f"[SYS] Physical Memory: {ram.percent}% used ({round(ram.used / (1024*1024*1024), 1)}GB)",
                    f"[NET] Total Data Transferred: {net_mb} MB",
                    "[SYS] Allocating extra memory to AI clusters...",
                    "[AI] Gemini cognitive core linked...",
                    "<span style='color: var(--color-warning);'>[USR] Live connection established</span>",
                ]
                
                if cpu > 80:
                    alerts.append("<span style='color: var(--color-alert);'>[SEC] WARNING: CPU usage critically high!</span>")
                if ram.percent > 90:
                    alerts.append("<span style='color: var(--color-alert);'>[SEC] WARNING: Memory usage critically high!</span>")
                    
                log_entry = random.choice(alerts)
                
                # Count real users in database instead of random number
                real_user_count = User.query.count()
                
                payload = {
                    'cpu': cpu,
                    'users': real_user_count,
                    'network': net_mb,
                    'log': log_entry
                }
                
                socketio.emit('admin_stats', payload, room='admin_room')
            except Exception as e:
                print(f"Error in admin live feed: {e}")

bg_thread = threading.Thread(target=admin_live_feed, daemon=True)
bg_thread.start()

def life_planner_engine():
    """Background task to scan upcoming events and send live alerts."""
    with app.app_context():
        while True:
            time.sleep(30)
            now_dt = datetime.datetime.now()
            today = now_dt.date()
            try:
                events = Event.query.filter_by(date=today).all()
                for evt in events:
                    if evt.time:
                        evt_dt = datetime.datetime.combine(today, evt.time)
                        delta = (evt_dt - now_dt).total_seconds() / 60.0
                        
                        
                        user_obj = db.session.get(User, evt.user_id)
                        play_audio = user_obj.read_notifications_aloud if user_obj else True
                        
                        if 59 <= delta < 60:
                            msg = f"Hey, your event '{evt.title}' starts in 1 hour."
                            socketio.emit('life_alert', {'message': msg, 'type': 'alert', 'play_audio': play_audio}, room=f'user_{evt.user_id}')
                        elif 14 <= delta < 15:
                            msg = f"Get ready! '{evt.title}' starts in 15 minutes."
                            socketio.emit('life_alert', {'message': msg, 'type': 'warning', 'play_audio': play_audio}, room=f'user_{evt.user_id}')
                        elif 0 <= delta < 1:
                            msg = f"It's time to begin: '{evt.title}'!"
                            socketio.emit('life_alert', {'message': msg, 'type': 'success', 'play_audio': play_audio}, room=f'user_{evt.user_id}')
            except Exception as e:
                pass # Prevent DB session errors from crashing thread

bg_thread2 = threading.Thread(target=life_planner_engine, daemon=True)
bg_thread2.start()

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if not user_id:
        return False # Reject connection
    
    # We must use db.session within app context normally, 
    # but socketio handlers have app context implicitly if using Flask-SocketIO.
    user = db.session.get(User, user_id)
    if not user:
        return False
        
    join_room(f"user_{user.id}")
    
    if user.is_admin:
        join_room('admin_room')

@socketio.on('disconnect')
def handle_disconnect():
    pass

# --- MIDDLEWARE ---

@app.before_request
def check_banned_ip():
    global GLOBAL_LOCKDOWN
    
    ip = get_client_ip()
    if BannedIP.query.filter_by(ip_address=ip).first():
        abort(403, description="Your IP has been permanently banned from this server.")
        
    user = None
    if session.get('user_id'):
        user = db.session.get(User, session.get('user_id'))
        if user and user.is_banned:
            session.clear()
            abort(403, description="Your account has been banned.")
            
    # Check Global Lockdown
    if GLOBAL_LOCKDOWN:
        if not user or not user.is_admin:
            if request.endpoint != 'login':
                abort(503, description="System is currently under emergency lockdown. All access is restricted.")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        user = db.session.get(User, session.get('user_id'))
        if not user or not user.is_admin: abort(403)
        return f(*args, **kwargs)
    return decorated_function

def check_onboarding(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = db.session.get(User, session.get('user_id'))
        if user and not user.onboarding_completed and request.endpoint not in ['login', 'register', 'onboarding', 'verify_method', 'send_code', 'verify_code', 'logout']:
            return redirect(url_for('onboarding'))
        return f(*args, **kwargs)
    return decorated_function

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def get_ip_location(ip):
    try:
        if ip in ['127.0.0.1', '::1', 'localhost']: return "Localhost Development"
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=2).json()
        if res.get('status') == 'success':
            return f"{res.get('city')}, {res.get('country')} (ISP: {res.get('isp')})"
    except: pass
    return "Unknown Location"

def check_vpn(ip):
    if ip in ['127.0.0.1', '::1', 'localhost']: return False
    try:
        res = requests.get(f"https://ipwho.is/{ip}", timeout=2).json()
        if res.get('success'):
            sec = res.get('security', {})
            if sec.get('vpn') or sec.get('proxy') or sec.get('tor'):
                return True
    except: pass
    return False

def generate_profile_id():
    while True:
        pid = str(random.randint(100000, 999999))
        if not User.query.filter_by(profile_id=pid).first():
            return pid

# --- HONEYPOT ROUTES ---

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/wp-admin')
@app.route('/admin/phpmyadmin')
@app.route('/.env')
@app.route('/database.sql')
def honeypot():
    ip = get_client_ip()
    banned = BannedIP(ip_address=ip, reason="Touched honeypot route: " + request.path)
    db.session.add(banned)
    db.session.commit()
    abort(403, description="Malicious activity detected. IP Blacklisted.")

# --- ROUTES ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    countries = sorted([country.name for country in pycountry.countries])
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        country = request.form.get('country')
        password = request.form.get('password')
        avatar = request.form.get('avatar_selection')
        preferred_language = request.form.get('preferred_language', 'en')
        
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error="Email already registered", countries=countries)
            
        filename = avatar if avatar else "default.png"
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
        ip = get_client_ip()
        loc = get_ip_location(ip)

        session['temp_user'] = {
            'name': name, 'email': email, 'phone_number': phone_number, 'country': country,
            'password_hash': generate_password_hash(password), 'profile_image': filename,
            'ip_address': ip, 'location_data': loc, 'preferred_language': preferred_language
        }
        
        return redirect(url_for('verify_method'))
    return render_template('register.html', countries=countries)

@app.route('/verify_method', methods=['GET'])
def verify_method():
    if 'temp_user' not in session: return redirect(url_for('register'))
    return render_template('verify_method.html', user=session['temp_user'])

@app.route('/send_code', methods=['POST'])
def send_code():
    if 'temp_user' not in session: return redirect(url_for('register'))
    method = request.form.get('method')
    user = session['temp_user']
    
    code = str(random.randint(100000, 999999))
    expires = datetime.datetime.now() + datetime.timedelta(minutes=10)
    
    vc = VerificationCode(email=user['email'], phone_number=user['phone_number'], code=code, expires_at=expires)
    db.session.add(vc)
    db.session.commit()
    
    print(f"\n=============================================")
    print(f"MOCK {method.upper()} SENT TO {user['email'] if method == 'email' else user['phone_number']}")
    print(f"YOUR VELA VERIFICATION CODE IS: {code}")
    print(f"=============================================\n")
    
    return redirect(url_for('verify_code'))

@app.route('/verify_code', methods=['GET', 'POST'])
def verify_code():
    if 'temp_user' not in session: return redirect(url_for('register'))
    
    if request.method == 'POST':
        code_input = request.form.get('code')
        user_data = session['temp_user']
        
        vc = VerificationCode.query.filter_by(email=user_data['email']).order_by(VerificationCode.id.desc()).first()
        if vc and vc.code == code_input and vc.expires_at > datetime.datetime.now():
            user = User(
                profile_id=generate_profile_id(),
                name=user_data['name'], email=user_data['email'], phone_number=user_data['phone_number'],
                country=user_data['country'], password_hash=user_data['password_hash'], 
                profile_image=user_data['profile_image'], ip_address=user_data['ip_address'],
                preferred_language=user_data['preferred_language'],
                last_login=datetime.datetime.now()
            )
            db.session.add(user)
            db.session.commit()
            
            log = ActivityLog(user_id=user.id, action="Registered & Verified", ip_address=user_data['ip_address'], location_data=user_data['location_data'])
            db.session.add(log)
            db.session.commit()
            
            session.pop('temp_user')
            session['user_id'] = user.id
            resp = make_response(redirect(url_for('onboarding')))
            resp.set_cookie('googtrans', f"/en/{user.preferred_language}")
            return resp
        else:
            return render_template('verify_code.html', error="Invalid or expired code.")
            
    return render_template('verify_code.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        is_oauth = request.form.get('is_oauth') == 'true'
        
        user = User.query.filter_by(email=email).first()
        
        ip = get_client_ip()
        loc = get_ip_location(ip)
        
        # Mock OAuth Creation
        if is_oauth and not user:
            user = User(
                profile_id=generate_profile_id(),
                name="Mock OAuth User",
                email=email,
                phone_number=None, # Intentional None to trigger Verification Alert
                country="US",
                password_hash=generate_password_hash(password),
                profile_image="default.png",
                ip_address=ip,
                last_login=datetime.datetime.now()
            )
            db.session.add(user)
            db.session.commit()
        
        if user:
            if user.is_banned:
                return render_template('login.html', error="Account suspended. Contact support.")
                
            if check_password_hash(user.password_hash, password):
                session['user_id'] = user.id
                user.last_login = datetime.datetime.now()
                log = ActivityLog(user_id=user.id, action="Logged In", ip_address=ip, location_data=loc)
                db.session.add(log)
                db.session.commit()
                
                # Emit live event to admins
                socketio.emit('admin_alert', {'message': f'User logged in: {user.email}'}, room='admin_room')
                
                if check_vpn(ip):
                    session['vpn_alert'] = "High Risk Session detected: VPN/Proxy usage identified. Please verify your identity."

                if user.is_admin:
                    resp = make_response(redirect(url_for('admin_dashboard')))
                else:
                    resp = make_response(redirect(url_for('dashboard')))
                resp.set_cookie('googtrans', f"/en/{user.preferred_language}")
                return resp
            else:
                log = ActivityLog(user_id=user.id, action="Failed Login Attempt", ip_address=ip, location_data=loc)
                db.session.add(log)
                db.session.commit()
                
        return render_template('login.html', error="Invalid Email or Password")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.occupation = request.form.get('occupation')
        user.age_group = request.form.get('age_group')
        user.goals = request.form.get('goals')
        user.onboarding_completed = True
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('onboarding.html')

@app.route('/')
@app.route('/dashboard')
@login_required
@check_onboarding
def dashboard():
    user = db.session.get(User, session['user_id'])
    needs_phone = user.phone_number is None or user.phone_number.strip() == ""
    vpn_alert = session.pop('vpn_alert', None)
    return render_template('dashboard.html', profile=user, needs_phone=needs_phone, vpn_alert=vpn_alert)

@app.route('/admin/lockdown', methods=['POST'])
@admin_required
def admin_lockdown():
    global GLOBAL_LOCKDOWN
    GLOBAL_LOCKDOWN = not GLOBAL_LOCKDOWN
    return redirect(url_for('admin_dashboard'))

@app.route('/update_phone', methods=['POST'])
@login_required
def update_phone():
    user = db.session.get(User, session['user_id'])
    phone = request.form.get('phone_number')
    if phone:
        user.phone_number = phone
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/support')
@login_required
def support():
    user = db.session.get(User, session['user_id'])
    return render_template('support.html', profile=user)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = db.session.get(User, session['user_id'])
    msg = None
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        ai_personality = request.form.get('ai_personality')
        preferred_language = request.form.get('preferred_language')
        
        updated = False
        if ai_personality and ai_personality != user.ai_personality:
            user.ai_personality = ai_personality
            updated = True
        
        if preferred_language and preferred_language != user.preferred_language:
            user.preferred_language = preferred_language
            updated = True
            
        read_aloud = 'read_notifications_aloud' in request.form
        if read_aloud != user.read_notifications_aloud:
            user.read_notifications_aloud = read_aloud
            updated = True
            
        if current_password and new_password:
            if check_password_hash(user.password_hash, current_password):
                user.password_hash = generate_password_hash(new_password)
                updated = True
            else:
                msg = "Incorrect current password."
                
        if updated and not msg:
            ip = get_client_ip()
            loc = get_ip_location(ip)
            log = ActivityLog(user_id=user.id, action="Updated Settings", ip_address=ip, location_data=loc)
            db.session.add(log)
            db.session.commit()
            msg = "Settings updated successfully!"
            
            resp = make_response(render_template('settings.html', profile=user, message=msg))
            if preferred_language:
                resp.set_cookie('googtrans', f"/en/{user.preferred_language}")
            return resp
            
    return render_template('settings.html', profile=user, message=msg)

@app.route('/schedule', methods=['GET', 'POST'])
@login_required
def schedule():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        title = request.form.get('title')
        desc = request.form.get('description')
        d_str = request.form.get('date')
        t_str = request.form.get('time')
        
        if title and d_str and t_str:
            d = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
            t = datetime.datetime.strptime(t_str, "%H:%M").time()
            evt = Event(user_id=user.id, title=title, description=desc, date=d, time=t)
            db.session.add(evt)
            db.session.commit()
            return redirect(url_for('schedule'))
            
    events = Event.query.filter_by(user_id=user.id).order_by(Event.date.asc(), Event.time.asc()).all()
    return render_template('schedule.html', profile=user, events=events)

@app.route('/health', methods=['GET', 'POST'])
@login_required
def health():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        d_str = request.form.get('date')
        w_lbs = request.form.get('weight_lbs', type=float)
        cals = request.form.get('calories', type=int)
        water = request.form.get('water_glasses', type=int)
        notes = request.form.get('workout_notes')
        
        if d_str:
            d = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
            log = HealthLog.query.filter_by(user_id=user.id, date=d).first()
            if not log:
                log = HealthLog(user_id=user.id, date=d)
                db.session.add(log)
            log.weight_lbs = w_lbs
            log.calories = cals
            log.water_glasses = water
            log.workout_notes = notes
            db.session.commit()
            return redirect(url_for('health'))
            
    today = datetime.date.today()
    logs = HealthLog.query.filter_by(user_id=user.id).order_by(HealthLog.date.desc()).all()
    today_log = HealthLog.query.filter_by(user_id=user.id, date=today).first()
    return render_template('health.html', profile=user, logs=logs, today_log=today_log, today=today.strftime("%Y-%m-%d"))

@app.route('/automations', methods=['GET', 'POST'])
@login_required
def automations():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            task = request.form.get('task_name')
            freq = request.form.get('frequency', 'Daily')
            if task:
                r = Routine(user_id=user.id, task_name=task, frequency=freq)
                db.session.add(r)
                db.session.commit()
        elif action == 'toggle':
            rid = request.form.get('routine_id', type=int)
            r = db.session.get(Routine, rid)
            if r and r.user_id == user.id:
                today = datetime.date.today()
                if r.last_completed == today:
                    r.last_completed = None
                    user.xp = max(0, user.xp - 50)
                else:
                    r.last_completed = today
                    user.xp += 50
                    user.level = (user.xp // 500) + 1
                db.session.commit()
        elif action == 'delete':
            rid = request.form.get('routine_id', type=int)
            r = db.session.get(Routine, rid)
            if r and r.user_id == user.id:
                db.session.delete(r)
                db.session.commit()
        return redirect(url_for('automations'))

    routines = Routine.query.filter_by(user_id=user.id).all()
    today = datetime.date.today()
    return render_template('automations.html', profile=user, routines=routines, today=today)

@app.route('/finance')
@login_required
def finance():
    user = db.session.get(User, session['user_id'])
    return render_template('finance.html', profile=user)

@app.route('/memory')
@login_required
def memory():
    user = db.session.get(User, session['user_id'])
    return render_template('memory.html', profile=user)

@app.route('/gamification')
@login_required
def gamification():
    user = db.session.get(User, session['user_id'])
    return render_template('gamification.html', profile=user)

@app.route('/insights')
@login_required
def insights():
    user = db.session.get(User, session['user_id'])
    return render_template('insights.html', profile=user)

@app.route('/api/generate_insights')
@login_required
def api_generate_insights():
    user = db.session.get(User, session['user_id'])
    
    health_logs = HealthLog.query.filter_by(user_id=user.id).order_by(HealthLog.date.desc()).limit(14).all()
    events = Event.query.filter_by(user_id=user.id).all()
    routines = Routine.query.filter_by(user_id=user.id).all()
    
    data_dump = f"Health History: {[h.date.strftime('%Y-%m-%d') + ' ' + str(h.weight_lbs) + 'lbs' for h in health_logs]}\n"
    data_dump += f"Events: {[e.title for e in events]}\n"
    data_dump += f"Routines: {[r.task_name for r in routines]}\n"
    
    prompt = f"Analyze the following data and provide 3 'Life Patterns' you have detected about the user. Focus on productivity, health, and schedule. Keep it concise, formatted as HTML paragraphs with bold titles. No markdown code blocks.\n\nData:\n{data_dump}"
    
    try:
        response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=[prompt])
        return jsonify({'status': 'success', 'html': response.text})
    except:
        return jsonify({'status': 'error'})

@app.route('/trust', methods=['GET', 'POST'])
@login_required
def trust():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.allow_ai_calendar = request.form.get('allow_ai_calendar') == 'on'
        user.allow_ai_finances = request.form.get('allow_ai_finances') == 'on'
        db.session.commit()
        return redirect(url_for('trust'))
        
    logs = ActivityLog.query.filter(ActivityLog.user_id == user.id, ActivityLog.action.like('AI Action:%')).order_by(ActivityLog.timestamp.desc()).all()
    return render_template('trust.html', profile=user, ai_logs=logs)

# --- ADMIN DASHBOARD ---

@app.route('/vela-admin')
@admin_required
def admin_dashboard():
    query = request.args.get('q', '')
    if query:
        users = User.query.filter(
            (User.name.contains(query)) | 
            (User.phone_number.contains(query)) |
            (User.profile_id.contains(query)) |
            (User.email.contains(query))
        ).all()
    else:
        users = User.query.all()
        
    return render_template('admin.html', users=users, query=query)

@app.route('/vela-admin/user/<int:uid>')
@admin_required
def admin_user_detail(uid):
    user = db.session.get(User, uid)
    logs = ActivityLog.query.filter_by(user_id=uid).order_by(ActivityLog.timestamp.desc()).all()
    msgs = Message.query.filter_by(user_id=uid).order_by(Message.timestamp.desc()).all()
    return render_template('admin_detail.html', u=user, logs=logs, msgs=msgs)

@app.route('/vela-admin/ban/<int:uid>', methods=['POST'])
@admin_required
def admin_ban_user(uid):
    user = db.session.get(User, uid)
    if user:
        user.is_banned = not user.is_banned
        db.session.commit()
    return redirect(url_for('admin_dashboard'))


# --- PLAID & AI ROUTES ---

def get_plaid_balances(user_id):
    item = PlaidItem.query.filter_by(user_id=user_id).first()
    if not item: return None
    try:
        access_token = fernet.decrypt(item.encrypted_access_token).decode()
        req = AccountsGetRequest(access_token=access_token)
        res = plaid_client.accounts_get(req)
        balances = [f"{acc['name']}: ${acc['balances']['current']}" for acc in res['accounts']]
        return "\n".join(balances)
    except Exception as e:
        return None

def build_ai_prompt(user_id):
    user = db.session.get(User, user_id)
    now = datetime.datetime.now().strftime('%A, %Y-%m-%d %H:%M:%S')
    
    balances = get_plaid_balances(user.id)
    fin_text = f"Bank Balances:\n{balances}" if balances else "No bank connected."
    
    today = datetime.date.today()
    events = Event.query.filter_by(user_id=user.id, date=today).order_by(Event.time.asc()).all()
    schedule_text = "\nToday's Schedule:\n"
    if events:
        for e in events: schedule_text += f"- {e.time.strftime('%H:%M')}: {e.title} ({e.description})\n"
    else:
        schedule_text += "No events scheduled today.\n"
        
    health = HealthLog.query.filter_by(user_id=user.id).order_by(HealthLog.date.desc()).first()
    health_text = "\nRecent Health Data:\n"
    if health:
        health_text += f"Date logged: {health.date}. Weight: {health.weight_lbs} lbs. Calories: {health.calories}. Water: {health.water_glasses} glasses. Workout: {health.workout_notes}\n"
    else:
        health_text += "No health data logged recently.\n"

    routines = Routine.query.filter_by(user_id=user.id).all()
    routine_text = "\nDaily Routines & Habits:\n"
    missed_habits = []
    if routines:
        for r in routines:
            status = "Completed" if r.last_completed == today else "NOT COMPLETED"
            routine_text += f"- {r.task_name} ({r.frequency}): {status}\n"
            if status == "NOT COMPLETED":
                missed_habits.append(r.task_name)
    else:
        routine_text += "No routines set.\n"
        
    accountability_clause = ""
    if missed_habits:
        accountability_clause = f"CRITICAL ACCOUNTABILITY INSTRUCTION: The user has NOT completed the following daily routines today: {', '.join(missed_habits)}. You MUST proactively remind them to complete these habits in your response."

    personality_clause = f"Your personality is: {user.ai_personality}. Adapt your tone to match this."
    if user.ai_personality == 'Strict Mentor':
        personality_clause += " Be very direct, demanding, and do not sugarcoat things."
    elif user.ai_personality == 'Friendly Coach':
        personality_clause += " Be encouraging, supportive, and use emojis."
    else:
        personality_clause += " Be highly professional, concise, and efficient."

    smart_reply_clause = "SMART REPLY ENGINE: If the user pastes an email or text message and asks for a reply draft (or uses the 'Draft a reply' command), output 3 distinct versions: 1) Formal, 2) Casual, 3) Persuasive. Make them ready to copy-paste."

    language_clause = f"CRITICAL LANGUAGE INSTRUCTION: You MUST speak and respond fluently in the user's preferred language ({user.preferred_language}). If the user asks a question in a different language, reply in that language. You natively understand all languages including Spanish, German, Chinese, and Nigerian languages like Igbo, Hausa, and Yoruba."
    accountability_clause = f"ACCOUNTABILITY SYSTEM: {user.accountability_mode}. "
    if user.accountability_mode == 'Strict':
        accountability_clause += "You will enforce strict discipline. Deny requests to waste time. Call out the user if they haven't exercised or worked. "

    planner_clause = "PROACTIVE PLANNER ENGINE: If the user says 'Plan my week', 'Plan my day', or anything similar, DO NOT just give ideas. You must actively ask what they want to do on specific days, structure it, and write it to the calendar using the add_calendar_event tool. Once you use the tool to add an event, proudly tell the user you've scheduled it."

    comm_clause = "COMMUNICATION AGENT (STRICT): If the user asks you to send a message or make a call to a contact (e.g., 'tell Mr Jack I will be late', 'call Thomas'), FIRST draft the message/call-script, present it to the user, and explicitly ask: 'Is that okay by you? If yes, let me know so I can send it.' DO NOT use the send_communication tool until the user replies with 'yes' or explicitly confirms. Once confirmed, use the send_communication tool."

    system_prompt = f"""You are VELA, an elite Virtual Executive Life Assistant.
Current System Date & Time: {now}.
User Profile: ID #{user.profile_id}, Name: {user.name} from {user.country}. {user.age_group} {user.occupation}. Goals: {user.goals}. Preferred Language: {user.preferred_language}.
Gamification: Level {user.level}, XP {user.xp}.
{fin_text}
{schedule_text}
{health_text}
{routine_text}

CRITICAL PERSONALITY INSTRUCTIONS:
{personality_clause}
In addition, incorporate local slang/greetings for someone in {user.country} matching their demographic. 

CRITICAL ACCURACY INSTRUCTIONS: You MUST use your Google Search tool to verify ALL facts, current events, and dates before answering. Do not guess. Keep responses concise.

{accountability_clause}
{planner_clause}
{comm_clause}
{smart_reply_clause}
{language_clause}
"""
    return system_prompt

@app.route('/api/life_feed', methods=['GET'])
@login_required
def api_life_feed():
    user = db.session.get(User, session['user_id'])
    system_prompt = build_ai_prompt(user.id)
    
    # We ask Gemini to generate a short morning briefing specifically for the Life Feed
    prompt = "Generate a 'Morning Briefing' for my Life Feed. Format it as a short, punchy paragraph. Highlight my upcoming meetings, budget warnings (if any), and pending routines. Keep it under 3 sentences. Use my chosen personality tone."
    
    config = types.GenerateContentConfig(system_instruction=system_prompt)
    try:
        response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=[prompt], config=config)
        return jsonify({'status': 'success', 'briefing': response.text})
    except Exception as e:
        return jsonify({'status': 'error', 'briefing': 'Could not fetch your daily briefing right now.'})

@app.route('/api/balances', methods=['GET'])
@login_required
def api_balances():
    balances = get_plaid_balances(session['user_id'])
    if balances: return jsonify({'status': 'success', 'data': balances})
    return jsonify({'status': 'error', 'message': 'No accounts linked.'})

@app.route('/api/create_link_token', methods=['POST'])
@login_required
def create_link_token():
    try:
        req = LinkTokenCreateRequest(
            products=[Products('auth'), Products('transactions')],
            client_name="VELA",
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(client_user_id=str(session['user_id']))
        )
        res = plaid_client.link_token_create(req)
        return jsonify(res.to_dict())
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})

@app.route('/api/set_access_token', methods=['POST'])
@login_required
def set_access_token():
    public_token = request.json.get('public_token')
    try:
        req = ItemPublicTokenExchangeRequest(public_token=public_token)
        res = plaid_client.item_public_token_exchange(req)
        
        plaid_item = PlaidItem.query.filter_by(user_id=session['user_id']).first()
        if not plaid_item:
            plaid_item = PlaidItem(user_id=session['user_id'])
            db.session.add(plaid_item)
            
        plaid_item.encrypted_access_token = fernet.encrypt(res['access_token'].encode())
        db.session.commit()
        return jsonify({'status': 'success'})
    except plaid.ApiException as e:
        return jsonify({'error': str(e)})

add_calendar_event_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="add_calendar_event",
            description="Adds a new event to the user's schedule/calendar.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "title": types.Schema(type=types.Type.STRING),
                    "description": types.Schema(type=types.Type.STRING),
                    "date": types.Schema(type=types.Type.STRING, description="YYYY-MM-DD"),
                    "time": types.Schema(type=types.Type.STRING, description="HH:MM (24-hour)"),
                },
                required=["title", "description", "date", "time"]
            )
        )
    ]
)

change_language_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="change_language",
            description="Changes the user's preferred language setting in their profile. Use this if the user asks you to change the language you speak in.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "language_code": types.Schema(type=types.Type.STRING, description="The 2-letter ISO language code (e.g., 'en', 'es', 'fr', 'de')."),
                },
                required=["language_code"]
            )
        )
    ]
)

send_communication_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="send_communication",
            description="Sends an SMS, WhatsApp message, or phone call on behalf of the user to a contact.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "platform": types.Schema(type=types.Type.STRING, description="Must be one of: 'sms', 'whatsapp', 'call'"),
                    "contact_name": types.Schema(type=types.Type.STRING, description="The name of the contact."),
                    "message": types.Schema(type=types.Type.STRING, description="The message content or voice script to send."),
                },
                required=["platform", "contact_name", "message"]
            )
        )
    ]
)

def process_gemini_chat(user, contents, config):
    try:
        response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=contents, config=config)
        
        if response.function_calls:
            for fc in response.function_calls:
                if fc.name == "add_calendar_event":
                    if not user.allow_ai_calendar:
                        result = "Permission Denied: User has disabled AI Calendar Access in the Trust Layer."
                    else:
                        args = fc.args
                        try:
                            d = datetime.datetime.strptime(args['date'], "%Y-%m-%d").date()
                            t = datetime.datetime.strptime(args['time'], "%H:%M").time()
                            evt = Event(user_id=user.id, title=args['title'], description=args.get('description', ''), date=d, time=t)
                            db.session.add(evt)
                            
                            ip = get_client_ip()
                            loc = get_ip_location(ip)
                            log = ActivityLog(user_id=user.id, action=f"AI Action: Added event '{args['title']}' to calendar.", ip_address=ip, location_data=loc)
                            db.session.add(log)
                            db.session.commit()
                            result = "Successfully added to calendar."
                        except Exception as e:
                            result = f"Failed to add: {str(e)}"
                            
                elif fc.name == "change_language":
                    try:
                        user.preferred_language = fc.args['language_code']
                        db.session.commit()
                        result = f"Language successfully changed to {fc.args['language_code']}."
                    except Exception as e:
                        result = f"Failed to change language: {str(e)}"
                        
                elif fc.name == "send_communication":
                    try:
                        args = fc.args
                        platform = args['platform'].upper()
                        # Simulate sending communication
                        log_msg = f"Communication Sent [{platform}] to {args['contact_name']}: '{args['message']}'"
                        ip = get_client_ip()
                        loc = get_ip_location(ip)
                        log = ActivityLog(user_id=user.id, action=log_msg, ip_address=ip, location_data=loc)
                        db.session.add(log)
                        db.session.commit()
                        result = f"Successfully sent {platform} message to {args['contact_name']}."
                    except Exception as e:
                        result = f"Failed to send communication: {str(e)}"
                    
                    contents.append(types.Content(role='model', parts=[types.Part.from_function_call(name=fc.name, args=args)]))
                    contents.append(types.Content(role='user', parts=[types.Part.from_function_response(name=fc.name, response={"result": result})]))
                    
            response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=contents, config=config)
            
        return response.text
    except Exception as e:
        with open("error.log", "a") as f: f.write(f"GEMINI ERROR: {str(e)}\n")
        return "I'm having trouble connecting to my brain right now."

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    incoming_msg = request.json.get('message', '').strip()
    if not incoming_msg: return jsonify({'reply': "I didn't quite get that."})
        
    user = db.session.get(User, session['user_id'])
    
    ip = get_client_ip()
    loc = get_ip_location(ip)
    log = ActivityLog(user_id=user.id, action="Web Dashboard Chat", ip_address=ip, location_data=loc)
    db.session.add(log)
    db.session.commit()

    system_prompt = build_ai_prompt(user.id)
    history = Message.query.filter_by(user_id=user.id).order_by(Message.timestamp.asc()).limit(10).all()
    
    contents = []
    for msg in history:
        r = 'model' if msg.role == 'ai' else 'user'
        contents.append(types.Content(role=r, parts=[types.Part.from_text(text=msg.content)]))
        
    contents.append(types.Content(role='user', parts=[types.Part.from_text(text=incoming_msg)]))
    
    config = types.GenerateContentConfig(system_instruction=system_prompt, tools=[{'google_search': {}}, add_calendar_event_tool, change_language_tool, send_communication_tool])
    reply_text = process_gemini_chat(user, contents, config)
    
    db.session.add(Message(user_id=user.id, role='user', content=incoming_msg))
    db.session.add(Message(user_id=user.id, role='ai', content=reply_text))
    db.session.commit()
    
    return jsonify({'reply': reply_text})

@app.route('/webhook/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    raw_number = request.values.get('From', '')
    
    phone_number = raw_number.replace('whatsapp:', '').strip()
    user = User.query.filter_by(phone_number=phone_number).first()
    
    resp = MessagingResponse()
    if not user:
        resp.message("Hi! I am VELA. I don't recognize this phone number. Please register at the VELA web dashboard first!")
        return str(resp)

    if user.is_banned: return str(resp)

    ip = get_client_ip()
    loc = get_ip_location(ip)
    log = ActivityLog(user_id=user.id, action="WhatsApp Interaction", ip_address=ip, location_data=loc)
    db.session.add(log)
    db.session.commit()

    system_prompt = build_ai_prompt(user.id)
    history = Message.query.filter_by(user_id=user.id).order_by(Message.timestamp.asc()).limit(10).all()
    
    contents = []
    for msg in history:
        r = 'model' if msg.role == 'ai' else 'user'
        contents.append(types.Content(role=r, parts=[types.Part.from_text(text=msg.content)]))
        
    contents.append(types.Content(role='user', parts=[types.Part.from_text(text=incoming_msg)]))
    
    config = types.GenerateContentConfig(system_instruction=system_prompt, tools=[{'google_search': {}}, add_calendar_event_tool])
    reply_text = process_gemini_chat(user, contents, config)
    
    db.session.add(Message(user_id=user.id, role='user', content=incoming_msg))
    db.session.add(Message(user_id=user.id, role='ai', content=reply_text))
    db.session.commit()

    resp.message(reply_text)
    return str(resp)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5001, host='0.0.0.0', allow_unsafe_werkzeug=True)
