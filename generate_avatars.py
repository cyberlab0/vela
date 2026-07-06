import os

os.makedirs('static/avatars', exist_ok=True)
colors = ['#60a5fa', '#34d399', '#fbbf24', '#f87171']

for i, color in enumerate(colors):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="50" fill="{color}"/>
        <circle cx="50" cy="35" r="20" fill="white"/>
        <path d="M20,90 Q50,55 80,90" stroke="white" stroke-width="10" fill="none" stroke-linecap="round"/>
    </svg>'''
    with open(f'static/avatars/avatar{i+1}.svg', 'w') as f:
        f.write(svg)
