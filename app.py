import csv
import io
import json
import os
import secrets
import shutil
import sqlite3
import threading
import zipfile
from datetime import datetime, date, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'cancha.db'
INITIAL_XLSX = BASE_DIR / 'data' / 'base_alumnos.xlsx'
UPLOAD_DIR = BASE_DIR / 'uploads'
STATIC_DIR = BASE_DIR / 'static'
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin123')
PORT = int(os.environ.get('PORT', '5000'))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]

SESSIONS = {}
RESERVATION_LOCK = threading.Lock()
DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
DAY_INDEX = {day: idx for idx, day in enumerate(DAYS)}
TIME_SLOTS = [f'{h:02d}:00-{h+1:02d}:00' for h in range(8, 22)]


def is_postgres():
    return bool(DATABASE_URL)


def adapt_sql(sql):
    """Convierte placeholders SQLite (?) a PostgreSQL (%s)."""
    return sql.replace('?', '%s') if is_postgres() else sql


class DB:
    """Pequeña capa compatible con SQLite local y PostgreSQL en Render."""
    def __init__(self):
        self.kind = 'postgres' if is_postgres() else 'sqlite'
        if self.kind == 'postgres':
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError('Falta instalar psycopg. Ejecuta: pip install -r requirements.txt') from exc
            self.con = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            DB_PATH.parent.mkdir(exist_ok=True)
            self.con = sqlite3.connect(DB_PATH, timeout=30)
            self.con.row_factory = sqlite3.Row
            self.con.execute('PRAGMA foreign_keys=ON')
            self.con.execute('PRAGMA journal_mode=WAL')

    def execute(self, sql, params=()):
        return self.con.execute(adapt_sql(sql), params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.con.rollback()
            else:
                self.con.commit()
        finally:
            self.con.close()
        return False


def db():
    return DB()


def ensure_sqlite_schema():
    schema = '''
    CREATE TABLE IF NOT EXISTS students (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dni TEXT
    );
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start TEXT NOT NULL,
        day TEXT NOT NULL,
        slot TEXT NOT NULL,
        sport TEXT NOT NULL,
        captain_code TEXT,
        status TEXT NOT NULL DEFAULT 'ACTIVA',
        created_at TEXT NOT NULL,
        cancelled_at TEXT,
        cancelled_by TEXT
    );
    CREATE TABLE IF NOT EXISTS reservation_students (
        reservation_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY(reservation_id, code),
        FOREIGN KEY(reservation_id) REFERENCES reservations(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS closed_slots (
        week_start TEXT NOT NULL,
        day TEXT NOT NULL,
        slot TEXT NOT NULL,
        reason TEXT,
        PRIMARY KEY(week_start, day, slot)
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_slot
      ON reservations(week_start, day, slot) WHERE status='ACTIVA';
    CREATE INDEX IF NOT EXISTS idx_res_week_status ON reservations(week_start, status);
    CREATE INDEX IF NOT EXISTS idx_rs_code ON reservation_students(code);
    '''
    with db() as con:
        for statement in schema.split(';'):
            if statement.strip():
                con.execute(statement)
        con.execute("INSERT INTO settings(key,value) VALUES('open_hour','8') ON CONFLICT(key) DO NOTHING")


def migrate_legacy_sqlite_if_needed():
    """Elimina la antigua restricción UNIQUE por horario para conservar canceladas y permitir re-reserva."""
    if is_postgres() or not DB_PATH.exists():
        return
    raw = sqlite3.connect(DB_PATH)
    try:
        row = raw.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='reservations'").fetchone()
        if not row or 'UNIQUE(week_start, day, slot)' not in (row[0] or '').replace('\n', ' '):
            return
        raw.execute('PRAGMA foreign_keys=OFF')
        raw.execute('BEGIN')
        raw.executescript('''
        ALTER TABLE reservation_students RENAME TO reservation_students_legacy;
        ALTER TABLE reservations RENAME TO reservations_legacy;
        CREATE TABLE reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            day TEXT NOT NULL,
            slot TEXT NOT NULL,
            sport TEXT NOT NULL,
            captain_code TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVA',
            created_at TEXT NOT NULL,
            cancelled_at TEXT,
            cancelled_by TEXT
        );
        CREATE TABLE reservation_students (
            reservation_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY(reservation_id, code),
            FOREIGN KEY(reservation_id) REFERENCES reservations(id) ON DELETE CASCADE
        );
        INSERT INTO reservations(id,week_start,day,slot,sport,captain_code,status,created_at)
        SELECT id,week_start,day,slot,sport,captain_code,status,created_at FROM reservations_legacy;
        INSERT INTO reservation_students(reservation_id,code,name)
        SELECT reservation_id,code,name FROM reservation_students_legacy;
        DROP TABLE reservation_students_legacy;
        DROP TABLE reservations_legacy;
        CREATE UNIQUE INDEX uq_active_slot
          ON reservations(week_start, day, slot) WHERE status='ACTIVA';
        CREATE INDEX idx_res_week_status ON reservations(week_start, status);
        CREATE INDEX idx_rs_code ON reservation_students(code);
        ''')
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.execute('PRAGMA foreign_keys=ON')
        raw.close()


def ensure_postgres_schema():
    statements = [
        '''CREATE TABLE IF NOT EXISTS students (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dni TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS reservations (
            id BIGSERIAL PRIMARY KEY,
            week_start TEXT NOT NULL,
            day TEXT NOT NULL,
            slot TEXT NOT NULL,
            sport TEXT NOT NULL,
            captain_code TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVA',
            created_at TEXT NOT NULL,
            cancelled_at TEXT,
            cancelled_by TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS reservation_students (
            reservation_id BIGINT NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY(reservation_id, code)
        )''',
        '''CREATE TABLE IF NOT EXISTS closed_slots (
            week_start TEXT NOT NULL,
            day TEXT NOT NULL,
            slot TEXT NOT NULL,
            reason TEXT,
            PRIMARY KEY(week_start, day, slot)
        )''',
        '''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''',
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_slot ON reservations(week_start, day, slot) WHERE status='ACTIVA'",
        "CREATE INDEX IF NOT EXISTS idx_res_week_status ON reservations(week_start, status)",
        "CREATE INDEX IF NOT EXISTS idx_rs_code ON reservation_students(code)",
    ]
    with db() as con:
        for statement in statements:
            con.execute(statement)
        con.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancelled_at TEXT")
        con.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancelled_by TEXT")
        con.execute("INSERT INTO settings(key,value) VALUES('open_hour','8') ON CONFLICT(key) DO NOTHING")


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    DB_PATH.parent.mkdir(exist_ok=True)
    if is_postgres():
        ensure_postgres_schema()
    else:
        migrate_legacy_sqlite_if_needed()
        ensure_sqlite_schema()
    if INITIAL_XLSX.exists():
        with db() as con:
            count = con.execute('SELECT COUNT(*) c FROM students').fetchone()['c']
        if count == 0:
            import_students(INITIAL_XLSX)


def week_start_from(d=None):
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def parse_xlsx(path):
    ns = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('a:si', ns):
                text = ''.join(t.text or '' for t in si.findall('.//a:t', ns))
                shared.append(text)
        root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        rows = []
        for row in root.findall('.//a:row', ns):
            vals = []
            last_col = 0
            for c in row.findall('a:c', ns):
                ref = c.attrib.get('r', '')
                col = 0
                for ch in ref:
                    if ch.isalpha():
                        col = col * 26 + ord(ch.upper()) - 64
                    else:
                        break
                while last_col + 1 < col:
                    vals.append('')
                    last_col += 1
                v = c.find('a:v', ns)
                val = '' if v is None else v.text or ''
                if c.attrib.get('t') == 's' and val.isdigit():
                    val = shared[int(val)]
                vals.append(str(val).strip())
                last_col = col
            if any(vals):
                rows.append(vals)
        return rows


def parse_csv(path):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8-sig', errors='ignore')
    return list(csv.reader(io.StringIO(text)))


def import_students(path):
    ext = Path(path).suffix.lower()
    rows = parse_xlsx(path) if ext == '.xlsx' else parse_csv(path)
    if not rows:
        return 0
    header = [str(x).strip().lower() for x in rows[0]]

    def find(*names):
        for n in names:
            for i, h in enumerate(header):
                if n in h:
                    return i
        return None

    code_i = find('código', 'codigo', 'code')
    name_i = find('nombrecompleto', 'nombre completo', 'nombre', 'name')
    dni_i = find('dni', 'documento')
    if code_i is None or name_i is None:
        name_i, dni_i, code_i = 0, 1, 2
    inserted = 0
    with db() as con:
        con.execute('DELETE FROM students')
        for r in rows[1:]:
            if len(r) <= max(code_i, name_i):
                continue
            code = str(r[code_i]).strip().upper()
            name = str(r[name_i]).strip().upper()
            dni = str(r[dni_i]).strip() if dni_i is not None and len(r) > dni_i else ''
            if code and name:
                con.execute('''INSERT INTO students(code,name,dni) VALUES(?,?,?)
                    ON CONFLICT(code) DO UPDATE SET name=excluded.name,dni=excluded.dni''', (code, name, dni))
                inserted += 1
    return inserted


def esc(s):
    return str(s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def html_page(title, body, admin=False):
    nav = '<a href="/">Reservar</a><a href="/semana">Disponibilidad</a><a href="/admin">Administrador</a>'
    if admin:
        nav += '<a href="/logout">Salir</a>'
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#f97316"><title>{esc(title)}</title><link rel="stylesheet" href="/static/style.css"><script src="/static/app.js" defer></script></head><body><header><a class="brand" href="/"><span class="brand-mark">IN</span><span><strong>INLEARNING</strong><small>Reserva de Cancha</small></span></a><nav>{nav}</nav></header><main>{body}</main><footer><b>INLEARNING · Reserva de Cancha</b><span>Sistema semanal de gestión deportiva</span></footer></body></html>'''


def is_open_now():
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='open_hour'").fetchone()
    h = int(row['value'] if row else 8)
    return datetime.now().hour >= h


def reservation_rules_html():
    return '''<section class="rules card"><div class="section-kicker">CONDICIONES DE INSCRIPCIÓN</div><h2>Reserva responsable para todos</h2><div class="rule-grid"><div><b>1</b><span>Un código solo puede participar <strong>una vez por día</strong>.</span></div><div><b>2</b><span>No se permite inscribirse en <strong>dos días consecutivos</strong>.</span></div><div><b>3</b><span>Fútbol: <strong>5 a 8</strong> alumnos. Vóley: <strong>8 a 12</strong>.</span></div><div><b>4</b><span>Solo se aceptan códigos registrados en la base institucional.</span></div></div></section>'''


def current_week_table():
    ws = week_start_from().isoformat()
    with db() as con:
        res = con.execute('SELECT * FROM reservations WHERE week_start=? AND status=\'ACTIVA\'', (ws,)).fetchall()
        closed = con.execute('SELECT * FROM closed_slots WHERE week_start=?', (ws,)).fetchall()
    occupied = {(r['day'], r['slot']): r for r in res}
    closedmap = {(c['day'], c['slot']): c for c in closed}
    rows = ''
    for slot in TIME_SLOTS:
        tds = ''
        for day in DAYS:
            if (day, slot) in closedmap:
                raw_reason = closedmap[(day, slot)]['reason'] or 'Horario cerrado por administración'
                reason = esc(raw_reason)
                closed_label = '⚙ Mantenimiento' if 'manten' in raw_reason.lower() else '🔒 Cerrado'
                cell = f'<span class="badge closed" title="{reason}"><span class="badge-label">{closed_label}</span></span>'
            elif (day, slot) in occupied:
                r = occupied[(day, slot)]
                cell = f'<span class="badge busy"><span class="badge-label">● Reservado</span><small>{esc(r["sport"].title())}</small></span>'
            else:
                cell = f'<a class="badge free" href="/reservar?day={quote(day)}&slot={quote(slot)}" title="Seleccionar horario disponible"><span class="badge-label">✓ Disponible</span></a>'
            tds += f'<td>{cell}</td>'
        rows += f'<tr><th>{slot}</th>{tds}</tr>'
    legend = '<div class="availability-legend"><span class="legend-item legend-free"><i></i>Disponible</span><span class="legend-item legend-busy"><i></i>Reservado</span><span class="legend-item legend-closed"><i></i>Cerrado / mantenimiento</span></div>'
    return legend + f'<div class="table-wrap availability-table"><table class="week"><tr><th>Hora</th>' + ''.join(f'<th>{d}</th>' for d in DAYS) + f'</tr>{rows}</table></div>'


def db_label():
    return 'PostgreSQL' if is_postgres() else 'SQLite local'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[{datetime.now().strftime("%H:%M:%S")}] {self.address_string()} - {fmt % args}')

    def send(self, status, content, ctype='text/html; charset=utf-8', extra=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if isinstance(content, str):
            content = content.encode('utf-8')
        self.wfile.write(content)

    def redirect(self, path):
        self.send(302, b'', extra={'Location': path})

    def get_session(self):
        c = cookies.SimpleCookie(self.headers.get('Cookie'))
        sid = c.get('sid')
        return SESSIONS.get(sid.value) if sid else None

    def require_admin(self):
        return self.get_session() == 'admin'

    def read_post(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path.startswith('/static/'):
            f = STATIC_DIR / p.path.split('/static/', 1)[1]
            if f.exists() and f.is_file() and STATIC_DIR in f.resolve().parents:
                ctype = 'text/css; charset=utf-8' if f.suffix == '.css' else 'application/javascript; charset=utf-8'
                return self.send(200, f.read_bytes(), ctype)
            return self.send(404, 'No encontrado')

        if p.path == '/api/student':
            q = parse_qs(p.query)
            code = q.get('code', [''])[0].strip().upper()
            with db() as con:
                s = con.execute('SELECT * FROM students WHERE code=?', (code,)).fetchone()
            return self.send(200, json.dumps({'ok': bool(s), 'code': code, 'name': s['name'] if s else ''}), 'application/json; charset=utf-8')

        if p.path == '/':
            locked = '' if is_open_now() else '<div class="alert">⏰ Las inscripciones se habilitan desde las 8:00 a. m. Puedes revisar la disponibilidad mientras tanto.</div>'
            body = f'''<section class="hero"><div><span class="eyebrow">BIENESTAR · DEPORTE · COMUNIDAD</span><h1>Reserva tu cancha de forma rápida y justa.</h1><p>Consulta la semana, valida los códigos de tu equipo y confirma un horario disponible.</p><a class="btn white" href="/semana">Ver disponibilidad</a></div><div class="hero-badge"><span>5</span><small>días disponibles</small></div></section>{locked}{reservation_rules_html()}<section class="section-head"><div><span class="section-kicker">SEMANA ACTUAL</span><h2>Horarios disponibles</h2></div><a href="/semana">Ver tabla completa →</a></section>{current_week_table()}'''
            return self.send(200, html_page('Reservas INLEARNING', body, self.require_admin()))

        if p.path == '/semana':
            body = '<div class="page-title"><span class="section-kicker">DISPONIBILIDAD</span><h1>Uso semanal de la cancha</h1><p>Selecciona un horario marcado como disponible para iniciar la reserva.</p></div>' + current_week_table() + reservation_rules_html()
            return self.send(200, html_page('Disponibilidad semanal', body, self.require_admin()))

        if p.path == '/reservar':
            q = parse_qs(p.query)
            day = q.get('day', [''])[0]
            slot = q.get('slot', [''])[0]
            if day not in DAYS or slot not in TIME_SLOTS:
                return self.redirect('/semana')
            ws = week_start_from().isoformat()
            with db() as con:
                occupied = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA'", (ws, day, slot)).fetchone()
                closed = con.execute('SELECT reason FROM closed_slots WHERE week_start=? AND day=? AND slot=?', (ws, day, slot)).fetchone()
            if occupied or closed:
                return self.send(200, html_page('Horario no disponible', '<div class="alert error"><b>Ese horario ya no está disponible.</b><br>Actualiza la tabla y elige otro horario.</div><a class="btn" href="/semana">Volver a disponibilidad</a>', self.require_admin()))
            disabled = '' if is_open_now() else 'disabled'
            msg = '' if is_open_now() else '<div class="alert">Aún no se puede reservar. Las inscripciones se habilitan desde las 8:00 a. m.</div>'
            fields = ''.join(f'<div class="code-row"><label>Código {i}</label><input name="code{i}" class="student-code" autocomplete="off" placeholder="Ej. SM000000000"><small></small></div>' for i in range(1, 13))
            body = f'''<div class="page-title"><span class="section-kicker">NUEVA RESERVA</span><h1>{esc(day)} · {esc(slot)}</h1><p>Completa los códigos del equipo. La validación se realiza contra la base de alumnos.</p></div>{msg}<form class="card reserve-card" method="post" action="/reservar"><input type="hidden" name="day" value="{esc(day)}"><input type="hidden" name="slot" value="{esc(slot)}"><div class="sport-select"><label for="sport">Deporte</label><select name="sport" id="sport"><option value="futbol">Fútbol · 5 a 8 alumnos</option><option value="voley">Vóley · 8 a 12 alumnos</option></select></div><div class="inline-note">Importante: un código no puede repetirse el mismo día ni participar en reservas de días consecutivos.</div><div id="codes" class="grid-codes">{fields}</div><button class="btn wide" {disabled}>Confirmar reserva</button></form>'''
            return self.send(200, html_page('Nueva reserva', body, self.require_admin()))

        if p.path == '/admin':
            if not self.require_admin():
                body = '<form class="login card" method="post" action="/login"><div class="admin-icon">IN</div><span class="section-kicker">ACCESO RESTRINGIDO</span><h1>Panel administrador</h1><p class="muted">Gestiona reservas, ocupación y horarios de la cancha.</p><label>Usuario</label><input name="user" autocomplete="username" placeholder="Usuario" required><label>Contraseña</label><input name="password" type="password" autocomplete="current-password" placeholder="Contraseña" required><button class="btn wide">Ingresar</button></form>'
                return self.send(200, html_page('Administrador', body))
            return self.admin_page(parse_qs(p.query))

        if p.path == '/logout':
            c = cookies.SimpleCookie(self.headers.get('Cookie'))
            sid = c.get('sid')
            if sid:
                SESSIONS.pop(sid.value, None)
            return self.send(302, b'', extra={'Location': '/', 'Set-Cookie': 'sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict'})

        if p.path == '/export.csv':
            if not self.require_admin():
                return self.redirect('/admin')
            return self.export_csv()

        return self.send(404, html_page('No encontrado', '<div class="empty-state"><h1>Página no encontrada</h1><a class="btn" href="/">Volver al inicio</a></div>'))

    def admin_page(self, query=None):
        query = query or {}
        ws = week_start_from().isoformat()
        with db() as con:
            total_students = con.execute('SELECT COUNT(*) c FROM students').fetchone()['c']
            reservas = con.execute('''SELECT r.*,
                (SELECT COUNT(*) FROM reservation_students rs WHERE rs.reservation_id=r.id) participant_count
                FROM reservations r WHERE r.week_start=? ORDER BY r.id DESC''', (ws,)).fetchall()
            # El sistema opera de lunes a viernes. Los registros históricos de sábado
            # se conservan en la base, pero no se muestran ni cuentan en la semana activa.
            reservas = [r for r in reservas if r['day'] in DAYS]
            active = [r for r in reservas if r['status'] == 'ACTIVA']
            cancelled = [r for r in reservas if r['status'] == 'CANCELADA']
            closed_rows = [c for c in con.execute('SELECT * FROM closed_slots WHERE week_start=? ORDER BY day,slot', (ws,)).fetchall() if c['day'] in DAYS]
            participants = con.execute('''SELECT rs.reservation_id,rs.code,rs.name FROM reservation_students rs
                JOIN reservations r ON r.id=rs.reservation_id WHERE r.week_start=? ORDER BY rs.name''', (ws,)).fetchall()
        pmap = {}
        for p in participants:
            pmap.setdefault(p['reservation_id'], []).append(p)
        total_capacity = len(DAYS) * len(TIME_SLOTS) - len(closed_rows)
        occupancy = round((len(active) / total_capacity * 100), 1) if total_capacity > 0 else 0

        day_counts = {d: 0 for d in DAYS}
        hour_counts = {s.split('-')[0]: 0 for s in TIME_SLOTS}
        sport_counts = {'Fútbol': 0, 'Vóley': 0}
        for r in active:
            day_counts[r['day']] = day_counts.get(r['day'], 0) + 1
            hour_counts[r['slot'].split('-')[0]] = hour_counts.get(r['slot'].split('-')[0], 0) + 1
            sport_counts['Fútbol' if r['sport'] == 'futbol' else 'Vóley'] += 1

        cards = f'''<div class="stats"><div><span class="stat-icon">👥</span><b>{total_students}</b><small>Alumnos en base</small></div><div><span class="stat-icon">✅</span><b>{len(active)}</b><small>Reservas activas</small></div><div><span class="stat-icon">📊</span><b>{occupancy}%</b><small>Ocupación semanal</small></div><div><span class="stat-icon">✕</span><b>{len(cancelled)}</b><small>Canceladas</small></div></div>'''

        msg = query.get('msg', [''])[0]
        msg_html = f'<div class="alert success-alert">{esc(msg)}</div>' if msg else ''
        err = query.get('err', [''])[0]
        if err:
            msg_html += f'<div class="alert error">{esc(err)}</div>'

        rows = ''
        for r in reservas:
            plist = pmap.get(r['id'], [])
            students_html = ''.join(f'<li><b>{esc(p["code"])}</b> · {esc(p["name"])}</li>' for p in plist)
            status_class = 'status-occupied' if r['status'] == 'ACTIVA' else 'status-cancelled'
            action = ''
            if r['status'] == 'ACTIVA':
                action = f'''<form method="post" action="/cancel" class="cancel-form" onsubmit="return prepareCancel(this)"><input type="hidden" name="id" value="{r['id']}"><input type="hidden" name="reason" value=""><button class="danger small-btn">Cancelar</button></form>'''
            else:
                action = f'<span class="muted tiny">{esc(r["cancelled_at"] or "")}</span>'
            rows += f'''<tr><td><b>R-{int(r['id']):05d}</b></td><td>{esc(r['day'])}<small>{esc(r['slot'])}</small></td><td>{esc(r['sport'].title())}</td><td><span class="status-pill {status_class}">{('Reservado' if r['status'] == 'ACTIVA' else esc(r['status'].title()))}</span></td><td>{r['participant_count']}<details><summary>Ver alumnos</summary><ul class="student-list">{students_html}</ul></details></td><td>{esc(r['created_at'])}</td><td>{action}</td></tr>'''

        closed_html = ''.join(f'''<tr><td>{esc(c['day'])}</td><td>{esc(c['slot'])}</td><td>{esc(c['reason'] or 'Sin motivo')}</td><td><form method="post" action="/open-slot"><input type="hidden" name="day" value="{esc(c['day'])}"><input type="hidden" name="slot" value="{esc(c['slot'])}"><button class="secondary small-btn">Reabrir</button></form></td></tr>''' for c in closed_rows)
        day_options = ''.join(f'<option value="{d}">{d}</option>' for d in DAYS)
        slot_options = ''.join(f'<option value="{s}">{s}</option>' for s in TIME_SLOTS)
        stats_script = f'''<script>window.DASH_DATA={{days:{json.dumps(day_counts, ensure_ascii=False)},hours:{json.dumps(hour_counts, ensure_ascii=False)},sports:{json.dumps(sport_counts, ensure_ascii=False)}}};</script>'''

        body = f'''<div class="admin-heading"><div><span class="section-kicker">ADMINISTRACIÓN · {esc(db_label())}</span><h1>Control de la cancha</h1><p>Semana del {esc(ws)} · métricas calculadas solo con reservas activas.</p></div><a class="btn small" href="/export.csv">Exportar registros CSV</a></div>{msg_html}{cards}<section class="dashboard-grid"><div class="card chart-card"><div class="chart-title"><span>Uso por día</span><b>Histograma semanal</b></div><canvas id="chartDays" height="220"></canvas></div><div class="card chart-card"><div class="chart-title"><span>Uso por hora</span><b>Horas más solicitadas</b></div><canvas id="chartHours" height="220"></canvas></div></section><section class="dashboard-grid"><div class="card"><span class="section-kicker">GESTIÓN DE HORARIOS</span><h2>Cerrar un horario</h2><p class="muted">Los horarios cerrados no podrán ser reservados por los alumnos.</p><form method="post" action="/close-slot" class="form-grid"><label>Día<select name="day" required>{day_options}</select></label><label>Horario<select name="slot" required>{slot_options}</select></label><label class="full">Motivo<input name="reason" placeholder="Ej. mantenimiento, actividad institucional"></label><button class="btn full">Cerrar horario</button></form></div><div class="card"><span class="section-kicker">DISTRIBUCIÓN</span><h2>Reservas por deporte</h2><canvas id="chartSports" height="220"></canvas></div></section><section class="card"><div class="section-head compact"><div><span class="section-kicker">REGISTROS</span><h2>Reservas de esta semana</h2></div><span class="muted">{len(reservas)} registros</span></div><div class="table-wrap flat"><table class="admin-table"><tr><th>Reserva</th><th>Día / hora</th><th>Deporte</th><th>Estado</th><th>Alumnos</th><th>Creada</th><th>Acción</th></tr>{rows or '<tr><td colspan="7">Sin reservas todavía.</td></tr>'}</table></div></section><section class="card"><div class="section-head compact"><div><span class="section-kicker">BLOQUEOS</span><h2>Horarios cerrados</h2></div><span class="muted">{len(closed_rows)} cerrados</span></div><div class="table-wrap flat"><table><tr><th>Día</th><th>Hora</th><th>Motivo</th><th>Acción</th></tr>{closed_html or '<tr><td colspan="4">No hay horarios cerrados.</td></tr>'}</table></div></section><section class="card"><span class="section-kicker">BASE DE ALUMNOS</span><h2>Actualizar padrón</h2><form method="post" action="/upload" enctype="multipart/form-data" class="upload-row"><input type="file" name="file" accept=".xlsx,.csv" required><button class="btn">Subir base</button></form><p class="muted">Acepta Excel .xlsx o CSV con columnas NombreCompleto, DNI y Código.</p></section>{stats_script}'''
        return self.send(200, html_page('Panel administrador', body, True))

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == '/login':
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            if secrets.compare_digest(data.get('user', [''])[0], ADMIN_USER) and secrets.compare_digest(data.get('password', [''])[0], ADMIN_PASS):
                sid = secrets.token_urlsafe(32)
                SESSIONS[sid] = 'admin'
                return self.send(302, b'', extra={'Location': '/admin', 'Set-Cookie': f'sid={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800'})
            return self.send(200, html_page('Administrador', '<div class="alert error">Usuario o contraseña incorrectos.</div><a class="btn" href="/admin">Intentar de nuevo</a>'))

        if p.path == '/reservar':
            if not is_open_now():
                return self.send(200, html_page('Reservas cerradas', '<div class="alert">Las reservas se habilitan desde las 8:00 a. m.</div><a class="btn" href="/semana">Volver</a>'))
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            return self.create_reservation(data)

        if p.path == '/cancel':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            rid = data.get('id', [''])[0]
            reason = data.get('reason', [''])[0].strip()
            with db() as con:
                row = con.execute("SELECT id FROM reservations WHERE id=? AND status='ACTIVA'", (rid,)).fetchone()
                if row:
                    con.execute("UPDATE reservations SET status='CANCELADA',cancelled_at=?,cancelled_by=? WHERE id=?", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ADMIN_USER + (f' · {reason}' if reason else ''), rid))
            return self.redirect('/admin?msg=' + quote(f'Reserva R-{int(rid):05d} cancelada.' if str(rid).isdigit() else 'Reserva cancelada.'))

        if p.path == '/close-slot':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            day = data.get('day', [''])[0]
            slot = data.get('slot', [''])[0]
            reason = data.get('reason', [''])[0].strip()[:180]
            if day not in DAYS or slot not in TIME_SLOTS:
                return self.redirect('/admin?err=' + quote('Día u horario inválido.'))
            ws = week_start_from().isoformat()
            with db() as con:
                active = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA'", (ws, day, slot)).fetchone()
                if active:
                    return self.redirect('/admin?err=' + quote('Ese horario tiene una reserva activa. Cancélala antes de cerrar el horario.'))
                con.execute('''INSERT INTO closed_slots(week_start,day,slot,reason) VALUES(?,?,?,?)
                    ON CONFLICT(week_start,day,slot) DO UPDATE SET reason=excluded.reason''', (ws, day, slot, reason or 'Cerrado por administración'))
            return self.redirect('/admin?msg=' + quote(f'{day} {slot} cerrado correctamente.'))

        if p.path == '/open-slot':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            day = data.get('day', [''])[0]
            slot = data.get('slot', [''])[0]
            ws = week_start_from().isoformat()
            with db() as con:
                con.execute('DELETE FROM closed_slots WHERE week_start=? AND day=? AND slot=?', (ws, day, slot))
            return self.redirect('/admin?msg=' + quote(f'{day} {slot} volvió a estar disponible.'))

        if p.path == '/upload':
            if not self.require_admin():
                return self.redirect('/admin')
            return self.handle_upload()

        return self.send(404, 'No encontrado')

    def create_reservation(self, data):
        day = data.get('day', [''])[0]
        slot = data.get('slot', [''])[0]
        sport = data.get('sport', [''])[0]
        codes = [data.get(f'code{i}', [''])[0].strip().upper() for i in range(1, 13)]
        codes = [c for c in codes if c]
        minmax = {'futbol': (5, 8), 'voley': (8, 12)}
        if day not in DAYS or slot not in TIME_SLOTS or sport not in minmax:
            return self.send(400, html_page('Datos inválidos', '<div class="alert error">Datos de reserva inválidos.</div><a class="btn" href="/semana">Volver</a>'))
        mn, mx = minmax[sport]
        errors = []
        if len(codes) < mn:
            errors.append(f'Para {sport} se requieren mínimo {mn} alumnos.')
        if len(codes) > mx:
            errors.append(f'Para {sport} se permiten máximo {mx} alumnos.')
        if len(codes) != len(set(codes)):
            errors.append('No se permiten códigos repetidos dentro de la misma reserva.')

        ws = week_start_from().isoformat()
        with RESERVATION_LOCK:
            with db() as con:
                existing = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA'", (ws, day, slot)).fetchone()
                if existing:
                    errors.append('Ese horario ya está reservado.')
                closed = con.execute('SELECT reason FROM closed_slots WHERE week_start=? AND day=? AND slot=?', (ws, day, slot)).fetchone()
                if closed:
                    errors.append('Ese horario fue cerrado por administración.')

                students = {}
                if codes:
                    placeholders = ','.join('?' * len(codes))
                    q = f'SELECT * FROM students WHERE code IN ({placeholders})'
                    if is_postgres():
                        q += ' FOR UPDATE'
                    students = {r['code']: r for r in con.execute(q, codes).fetchall()}
                for c in codes:
                    if c not in students:
                        errors.append(f'Código no registrado: {c}')

                if codes:
                    placeholders = ','.join('?' * len(codes))
                    usage = con.execute(f'''SELECT rs.code,r.day,r.slot FROM reservation_students rs
                        JOIN reservations r ON r.id=rs.reservation_id
                        WHERE r.week_start=? AND r.status='ACTIVA' AND rs.code IN ({placeholders})''', [ws] + codes).fetchall()
                    target_idx = DAY_INDEX[day]
                    same_day = set()
                    consecutive = set()
                    for u in usage:
                        if u['day'] == day:
                            same_day.add(u['code'])
                        elif u['day'] in DAY_INDEX and abs(DAY_INDEX[u['day']] - target_idx) == 1:
                            consecutive.add(u['code'])
                    for c in sorted(same_day):
                        nm = students[c]['name'] if c in students else ''
                        errors.append(f'{c} · {nm}: ya tiene una inscripción activa el {day}.')
                    for c in sorted(consecutive):
                        nm = students[c]['name'] if c in students else ''
                        errors.append(f'{c} · {nm}: no puede inscribirse en dos días consecutivos.')

                if errors:
                    unique_errors = list(dict.fromkeys(errors))
                    items = ''.join(f'<li>{esc(e)}</li>' for e in unique_errors)
                    return self.send(200, html_page('No se pudo reservar', f'<div class="alert error"><b>No se pudo confirmar la reserva.</b><ul>{items}</ul></div><a class="btn" href="/semana">Elegir otro horario</a>'))

                created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    if is_postgres():
                        rid = con.execute('''INSERT INTO reservations(week_start,day,slot,sport,captain_code,created_at)
                            VALUES(?,?,?,?,?,?) RETURNING id''', (ws, day, slot, sport, codes[0], created_at)).fetchone()['id']
                    else:
                        cur = con.execute('''INSERT INTO reservations(week_start,day,slot,sport,captain_code,created_at)
                            VALUES(?,?,?,?,?,?)''', (ws, day, slot, sport, codes[0], created_at))
                        rid = cur.lastrowid
                    for c in codes:
                        con.execute('INSERT INTO reservation_students(reservation_id,code,name) VALUES(?,?,?)', (rid, c, students[c]['name']))
                except Exception as exc:
                    con.con.rollback()
                    print('Error al crear reserva:', exc)
                    return self.send(200, html_page('Horario no disponible', '<div class="alert error"><b>La reserva no pudo guardarse.</b><br>Es posible que otro usuario haya tomado el horario. Revisa la disponibilidad nuevamente.</div><a class="btn" href="/semana">Actualizar disponibilidad</a>'))

        names = ''.join(f'<li><b>{esc(c)}</b> · {esc(students[c]["name"])}</li>' for c in codes)
        return self.send(200, html_page('Reserva confirmada', f'''<section class="success reservation-success"><div class="success-check">✓</div><span class="section-kicker">RESERVA CONFIRMADA</span><h1>Tu horario quedó registrado</h1><p class="reservation-summary">{esc(day)} · {esc(slot)} · {esc(sport.title())}</p><div class="reservation-code">R-{int(rid):05d}</div><details><summary>Ver alumnos inscritos</summary><ul>{names}</ul></details><a class="btn" href="/semana">Volver a disponibilidad</a></section>'''))

    def handle_upload(self):
        raw = self.read_post()
        ctype = self.headers.get('Content-Type', '')
        boundary_text = ctype.split('boundary=')[-1]
        if not boundary_text or boundary_text == ctype:
            return self.redirect('/admin?err=' + quote('No se pudo leer el archivo.'))
        boundary = boundary_text.strip('"').encode()
        parts = raw.split(b'--' + boundary)
        saved = None
        for part in parts:
            if b'name="file"' in part and b'filename="' in part:
                try:
                    head, content = part.split(b'\r\n\r\n', 1)
                except ValueError:
                    continue
                filename = head.split(b'filename="')[1].split(b'"')[0].decode('utf-8', errors='ignore')
                ext = Path(filename).suffix.lower()
                if ext not in ['.xlsx', '.csv']:
                    continue
                saved = UPLOAD_DIR / ('base_importada' + ext)
                saved.write_bytes(content.rsplit(b'\r\n', 1)[0])
        if saved:
            try:
                n = import_students(saved)
                shutil.copy(saved, BASE_DIR / 'data' / ('base_alumnos' + saved.suffix))
                return self.redirect('/admin?msg=' + quote(f'Base actualizada correctamente: {n} alumnos cargados.'))
            except Exception as exc:
                print('Error importando base:', exc)
                return self.redirect('/admin?err=' + quote('No se pudo importar la base. Verifica las columnas y el formato.'))
        return self.redirect('/admin?err=' + quote('No se pudo subir el archivo. Usa .xlsx o .csv.'))

    def export_csv(self):
        ws = week_start_from().isoformat()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['Reserva', 'Semana', 'Día', 'Horario', 'Deporte', 'Estado', 'Código', 'Alumno', 'Creado', 'Cancelado', 'Cancelado por'])
        with db() as con:
            rows = con.execute('''SELECT r.id,r.week_start,r.day,r.slot,r.sport,r.status,rs.code,rs.name,r.created_at,r.cancelled_at,r.cancelled_by
                FROM reservations r JOIN reservation_students rs ON r.id=rs.reservation_id
                WHERE r.week_start=? ORDER BY r.id,rs.name''', (ws,)).fetchall()
        for r in rows:
            w.writerow([r['id'], r['week_start'], r['day'], r['slot'], r['sport'], r['status'], r['code'], r['name'], r['created_at'], r['cancelled_at'] or '', r['cancelled_by'] or ''])
        return self.send(200, out.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="reservas_semana.csv"'})


def main():
    init_db()
    print(f'✅ Sistema listo en http://127.0.0.1:{PORT} · Base: {db_label()}')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
