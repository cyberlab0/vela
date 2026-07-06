import os
import glob
import re

new_nav = '''<nav class="sidebar glass-panel">
        <div class="logo-area animate-pulse-glow"><h2>VELA</h2></div>
        <ul class="nav-links">
            <li><a href="{{ url_for('dashboard') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-home"></i> Home</a></li>
            <li><a href="{{ url_for('schedule') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-calendar-alt"></i> Schedule</a></li>
            <li><a href="{{ url_for('finance') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-wallet" style="color: var(--color-success)"></i> Finance</a></li>
            <li><a href="{{ url_for('memory') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-brain" style="color: var(--color-info)"></i> Second Brain</a></li>
            <li><a href="{{ url_for('health') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-heartbeat"></i> Health</a></li>
            <li><a href="{{ url_for('automations') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-bolt"></i> Routines</a></li>
            <li><a href="{{ url_for('gamification') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-trophy" style="color: var(--color-warning)"></i> Gamification</a></li>
            <li><a href="{{ url_for('insights') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-chart-pie"></i> AI Insights</a></li>
            <li><a href="{{ url_for('trust') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-shield-alt"></i> Security</a></li>
            <li><a href="{{ url_for('settings') }}" style="color: inherit; text-decoration: none;"><i class="fas fa-cog"></i> Settings</a></li>
        </ul>
        <div class="user-profile animate-fade-in">
            <div class="avatar">{{ profile.name[0].upper() if profile.name else 'U' }}</div>
            <div style="display: flex; flex-direction: column;">
                <span style="font-weight: 500;">{{ profile.name }}</span>
            </div>
            <a href="{{ url_for('logout') }}" class="logout-btn" style="margin-left: auto;"><i class="fas fa-sign-out-alt"></i></a>
        </div>
    </nav>'''

for file in glob.glob('templates/*.html'):
    if file in ['templates/login.html', 'templates/register.html', 'templates/verify_code.html', 'templates/onboarding.html']:
        continue
    
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace anything between <nav class="sidebar glass-panel"> and </nav>
    content = re.sub(r'<nav class="sidebar glass-panel">.*?</nav>', new_nav, content, flags=re.DOTALL)
    
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)
