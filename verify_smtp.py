from pathlib import Path
import smtplib

env_path = Path(r'e:\project\.env')
vals = {}
for raw in env_path.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    vals[key.strip()] = value.strip().strip('"').strip("'")

user = vals.get('SMTP_USERNAME')
pwd = vals.get('SMTP_PASSWORD')
host = vals.get('SMTP_HOST', 'smtp.gmail.com')
port = int(vals.get('SMTP_PORT', '587'))
print('SMTP_USERNAME =', user)
print('SMTP_HOST =', host)
print('SMTP_PORT =', port)
print('SMTP_FROM =', vals.get('SMTP_FROM'))

try:
    server = smtplib.SMTP(host, port, timeout=15)
    server.starttls()
    server.login(user, pwd)
    print('SMTP_LOGIN = SUCCESS')
    server.quit()
except Exception as exc:
    print('SMTP_LOGIN = FAILED')
    print(type(exc).__name__ + ': ' + str(exc))
