import sys
from app import app, db, User, ActivityLog, generate_profile_id
from werkzeug.security import generate_password_hash
import datetime

def init_admin():
    with app.app_context():
        # Clean db if needed
        db.create_all()
        
        if User.query.filter_by(email='master@vela.io').first():
            print("Admin already exists!")
            return
            
        password = "VELA_GOD_MODE_2026_!@#"
        admin = User(
            profile_id=generate_profile_id(),
            is_admin=True,
            name="Super Admin",
            email="master@vela.io",
            phone_number="+10000000000",
            country="United States",
            password_hash=generate_password_hash(password),
            profile_image="avatars/avatar1.svg",
            ip_address="127.0.0.1",
            last_login=datetime.datetime.now(),
            onboarding_completed=True
        )
        
        db.session.add(admin)
        db.session.commit()
        
        log = ActivityLog(user_id=admin.id, action="System Initialization - Super Admin Created", ip_address="127.0.0.1", location_data="Secure Server")
        db.session.add(log)
        db.session.commit()
        
        print("\n" + "="*50)
        print("FORT KNOX SECURITY ENABLED")
        print("="*50)
        print("MASTER ADMIN CREDENTIALS:")
        print(f"URL: http://127.0.0.1:5001/login")
        print(f"Email: master@vela.io")
        print(f"Password: {password}")
        print("="*50 + "\n")

if __name__ == '__main__':
    init_admin()
