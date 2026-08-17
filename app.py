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
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'Welcome05@@')
PORT = int(os.environ.get('PORT', '5000'))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]

SESSIONS = {}
RESERVATION_LOCK = threading.Lock()
DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
DAY_INDEX = {day: idx for idx, day in enumerate(DAYS)}
ALL_TIME_SLOTS = [f'{h:02d}:00-{h+1:02d}:00' for h in range(8, 22)]
SEAT_DAY = 'Lunes a viernes'
SEAT_SLOT = '09:00-22:00'
SEAT_HOURS_LABEL = '9:00 a. m. a 10:00 p. m.'

# VIVA permite crecer sin volver a cambiar la lógica principal.
# Cada actividad administra su propio horario mediante start_hour/end_hour.
# Aula de Diseño: ambiente 510, aforo 36 y atención desde las 11:00.
ACTIVITIES = {
    'futbol': {
        'label': 'Fútbol', 'icon': '⚽', 'kind': 'team', 'room': 'Cancha deportiva',
        'start_hour': 8, 'end_hour': 22, 'min': 5, 'max': 8,
        'description': 'Arma tu equipo y reserva la cancha.'
    },
    'voley': {
        'label': 'Vóley', 'icon': '🏐', 'kind': 'team', 'room': 'Cancha deportiva',
        'start_hour': 8, 'end_hour': 22, 'min': 8, 'max': 12,
        'description': 'Coordina tu equipo y vive el partido.'
    },
    'imac': {
        'label': 'Laboratorio Mac', 'icon': '🖥️', 'kind': 'seat', 'room': '105',
        'start_hour': 9, 'end_hour': 22, 'capacity': 40,
        'description': 'Reserva un cupo en el laboratorio Mac.'
    },
    'windows': {
        'label': 'Laboratorio Windows', 'icon': '🖥️', 'kind': 'seat', 'room': '210',
        'start_hour': 9, 'end_hour': 22, 'capacity': 40,
        'description': 'Reserva un cupo en el laboratorio Windows.'
    },
    'diseno': {
        'label': 'Aula de Cutting', 'icon': '✂️', 'kind': 'seat', 'room': '510',
        'start_hour': 9, 'end_hour': 22, 'capacity': 36,
        'description': 'Reserva uno de los 36 puestos del aula de Cutting.'
    },
}
SPORT_KEYS = ('futbol', 'voley')
ROOM_SETTING_KEYS = {
    'imac': 'room_imac',
    'windows': 'room_windows',
    'diseno': 'room_diseno',
}
SEAT_STATUS_KEYS = {
    'imac': ('status_imac', 'status_reason_imac'),
    'windows': ('status_windows', 'status_reason_windows'),
    'diseno': ('status_diseno', 'status_reason_diseno'),
}
SEAT_STATUS_LABELS = {
    'available': ('Disponible', '✅'),
    'closed': ('Cerrado', '🔒'),
    'maintenance': ('En mantenimiento', '🛠️'),
}



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
    CREATE TABLE IF NOT EXISTS activity_closed_slots (
        week_start TEXT NOT NULL,
        activity TEXT NOT NULL,
        day TEXT NOT NULL,
        slot TEXT NOT NULL,
        reason TEXT,
        PRIMARY KEY(week_start, activity, day, slot)
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_res_week_status ON reservations(week_start, status);
    CREATE INDEX IF NOT EXISTS idx_res_activity ON reservations(week_start, sport, day, slot, status);
    CREATE INDEX IF NOT EXISTS idx_rs_code ON reservation_students(code);
    '''
    with db() as con:
        for statement in schema.split(';'):
            if statement.strip():
                con.execute(statement)
        # El índice anterior hacía único TODO horario. VIVA necesita múltiples cupos en laboratorios.
        con.execute('DROP INDEX IF EXISTS uq_active_slot')
        con.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_active_sports_slot
            ON reservations(week_start, day, slot)
            WHERE status='ACTIVA' AND sport IN ('futbol','voley')''')
        con.execute("INSERT INTO settings(key,value) VALUES('open_hour','8') ON CONFLICT(key) DO NOTHING")


def migrate_legacy_sqlite_if_needed():
    """Migra una tabla muy antigua que tenía UNIQUE directo en el horario."""
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
        INSERT INTO reservations(id,week_start,day,slot,sport,captain_code,status,created_at,cancelled_at,cancelled_by)
        SELECT id,week_start,day,slot,sport,captain_code,status,created_at,NULL,NULL FROM reservations_legacy;
        INSERT INTO reservation_students(reservation_id,code,name)
        SELECT reservation_id,code,name FROM reservation_students_legacy;
        DROP TABLE reservation_students_legacy;
        DROP TABLE reservations_legacy;
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
        '''CREATE TABLE IF NOT EXISTS activity_closed_slots (
            week_start TEXT NOT NULL,
            activity TEXT NOT NULL,
            day TEXT NOT NULL,
            slot TEXT NOT NULL,
            reason TEXT,
            PRIMARY KEY(week_start, activity, day, slot)
        )''',
        '''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''',
        "CREATE INDEX IF NOT EXISTS idx_res_week_status ON reservations(week_start, status)",
        "CREATE INDEX IF NOT EXISTS idx_res_activity ON reservations(week_start, sport, day, slot, status)",
        "CREATE INDEX IF NOT EXISTS idx_rs_code ON reservation_students(code)",
    ]
    with db() as con:
        for statement in statements:
            con.execute(statement)
        con.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancelled_at TEXT")
        con.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancelled_by TEXT")
        con.execute('DROP INDEX IF EXISTS uq_active_slot')
        con.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_active_sports_slot
            ON reservations(week_start, day, slot)
            WHERE status='ACTIVA' AND sport IN ('futbol','voley')''')
        con.execute("INSERT INTO settings(key,value) VALUES('open_hour','8') ON CONFLICT(key) DO NOTHING")


def migrate_legacy_closures():
    """Conserva los cierres de la versión cancha, aplicándolos a Fútbol y Vóley."""
    with db() as con:
        try:
            legacy = con.execute('SELECT week_start,day,slot,reason FROM closed_slots').fetchall()
        except Exception:
            legacy = []
        for c in legacy:
            for activity in SPORT_KEYS:
                con.execute('''INSERT INTO activity_closed_slots(week_start,activity,day,slot,reason)
                    VALUES(?,?,?,?,?) ON CONFLICT(week_start,activity,day,slot) DO NOTHING''',
                    (c['week_start'], activity, c['day'], c['slot'], c['reason']))
        # Una vez migrados, vaciamos la tabla heredada para que un horario reabierto
        # no vuelva a cerrarse automáticamente en el siguiente reinicio.
        if legacy:
            con.execute('DELETE FROM closed_slots')


def load_room_settings():
    """Carga los números/nombres de ambiente editables por el administrador."""
    with db() as con:
        for activity, setting_key in ROOM_SETTING_KEYS.items():
            row = con.execute('SELECT value FROM settings WHERE key=?', (setting_key,)).fetchone()
            if row and str(row['value']).strip():
                ACTIVITIES[activity]['room'] = str(row['value']).strip()


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    DB_PATH.parent.mkdir(exist_ok=True)
    if is_postgres():
        ensure_postgres_schema()
    else:
        migrate_legacy_sqlite_if_needed()
        ensure_sqlite_schema()
    migrate_legacy_closures()
    load_room_settings()
    if INITIAL_XLSX.exists():
        with db() as con:
            count = con.execute('SELECT COUNT(*) c FROM students').fetchone()['c']
        if count == 0:
            import_students(INITIAL_XLSX)


def week_start_from(d=None):
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def slots_for(activity):
    cfg = ACTIVITIES[activity]
    return [f'{h:02d}:00-{h+1:02d}:00' for h in range(cfg['start_hour'], cfg['end_hour'])]


def activity_label(activity):
    return ACTIVITIES.get(activity, {}).get('label', activity.title() if activity else '')


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


def loader_html():
    return '''<div id="viva-loader" class="viva-loader" aria-hidden="true">
      <div class="loader-glow"></div>
      <div class="loader-content">
        <div id="loader-icon" class="loader-activity-icon">⚽</div>
        <div class="viva-flag">VIVA</div>
        <div class="viva-signature">Vive tu campus.</div>
        <small id="loader-copy">Preparando tu experiencia...</small>
      </div>
    </div>'''


def html_page(title, body, admin=False):
    nav = '<a href="/">Inicio</a><a href="/semana?activity=futbol">Disponibilidad</a><a href="/admin">Administrador</a>'
    if admin:
        nav += '<a href="/logout">Salir</a>'
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#f97316"><title>{esc(title)}</title><link rel="stylesheet" href="/static/style.css"><script src="/static/app.js" defer></script></head><body><header><a class="brand viva-brand" href="/"><span class="brand-mark viva-mark">V</span><span><strong>VIVA</strong><small>Vive tu campus.</small></span></a><nav>{nav}</nav></header><main>{body}</main><footer><b>VIVA</b><span>Reserva. Participa. VIVE.</span><em>Vive tu campus.</em></footer>{loader_html()}</body></html>'''


def is_open_now():
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='open_hour'").fetchone()
    h = int(row['value'] if row else 8)
    return datetime.now().hour >= h


def seat_availability(activity, ws=None):
    # Devuelve ocupados y aforo disponible real del ambiente en la semana actual.
    cfg = ACTIVITIES[activity]
    if cfg.get('kind') != 'seat':
        return 0, 0
    ws = ws or week_start_from().isoformat()
    with db() as con:
        used = seat_used(con, ws, activity)
    remaining = max(0, cfg['capacity'] - used)
    return used, remaining


def seat_admin_status(activity):
    """Estado general editable por el admin para Mac, Windows y Cutting."""
    if activity not in SEAT_STATUS_KEYS:
        return 'available', ''
    status_key, reason_key = SEAT_STATUS_KEYS[activity]
    with db() as con:
        srow = con.execute('SELECT value FROM settings WHERE key=?', (status_key,)).fetchone()
        rrow = con.execute('SELECT value FROM settings WHERE key=?', (reason_key,)).fetchone()
    status = str(srow['value']).strip() if srow and srow['value'] else 'available'
    if status not in SEAT_STATUS_LABELS:
        status = 'available'
    reason = str(rrow['value']).strip() if rrow and rrow['value'] else ''
    return status, reason


def seat_status_badge(activity, compact=False):
    status, reason = seat_admin_status(activity)
    label, icon = SEAT_STATUS_LABELS[status]
    cls = f'seat-global-status status-{status}' + (' compact' if compact else '')
    detail = f'<small>{esc(reason)}</small>' if reason else ''
    return f'<span class="{cls}"><b>{icon} {esc(label)}</b>{detail}</span>'


def activity_cards_html():
    cards = []
    ws = week_start_from().isoformat()
    for key, cfg in ACTIVITIES.items():
        if cfg['kind'] == 'seat':
            used, remaining = seat_availability(key, ws)
            admin_status, admin_reason = seat_admin_status(key)
            if admin_status == 'available':
                state = 'AFORO COMPLETO' if remaining <= 0 else 'AFORO DISPONIBLE'
                extra = f'<span class="home-aforo"><strong>{remaining}</strong><span>{state}</span><em>de {cfg["capacity"]}</em></span>'
            else:
                status_label, status_icon = SEAT_STATUS_LABELS[admin_status]
                reason_html = f'<em>{esc(admin_reason)}</em>' if admin_reason else '<em>No admite nuevas reservas</em>'
                extra = f'<span class="home-aforo home-status-{admin_status}"><strong>{status_icon}</strong><span>{esc(status_label).upper()}</span>{reason_html}</span>'
            description = ''
            card_class = f'activity-card activity-card-{key} seat-card'
        else:
            extra = f'<span class="activity-meta">{cfg["min"]} a {cfg["max"]} alumnos</span>'
            description = f'<small>{esc(cfg["description"])}</small>'
            card_class = f'activity-card activity-card-{key} sport-card'
        cards.append(f'''<a class="{card_class}" href="/semana?activity={quote(key)}" data-activity="{key}" data-icon="{esc(cfg['icon'])}" data-label="{esc(cfg['label'])}">
            <span class="activity-icon activity-icon-{key}">{esc(cfg['icon'])}</span>
            <span class="activity-copy"><b>{esc(cfg['label'])}</b>{description}{extra}</span>
            <span class="activity-arrow" aria-hidden="true">→</span>
        </a>''')
    return '<div class="activity-grid">' + ''.join(cards) + '</div>'


def room_focus_html(cfg, compact=False):
    # En el encabezado de laboratorios se resalta el ambiente configurado por el admin.
    if cfg.get('kind') != 'seat' or not cfg.get('room'):
        return ''
    activity = next((k for k, v in ACTIVITIES.items() if v is cfg), None)
    title = 'LABORATORIO' if activity in ('imac', 'windows') else 'AULA'
    cls = 'space-focus compact room-identity-focus' if compact else 'space-focus room-identity-focus'
    room_value = esc(cfg['room'])
    return f'''<aside class="{cls}" aria-label="Ambiente {room_value}">
        <span>{title}</span>
        <strong>{room_value}</strong>
        <small>SALÓN DISPONIBLE</small>
    </aside>'''


def activity_selector(active):
    items = []
    for key, cfg in ACTIVITIES.items():
        cls = 'activity-tab active' if key == active else 'activity-tab'
        items.append(f'<a class="{cls}" href="/semana?activity={quote(key)}" data-activity="{key}" data-icon="{esc(cfg["icon"])}"><span>{esc(cfg["icon"])}</span>{esc(cfg["label"])}</a>')
    return '<div class="activity-tabs">' + ''.join(items) + '</div>'


def reservation_rules_html(activity):
    cfg = ACTIVITIES[activity]
    if cfg['kind'] == 'team':
        return f'''<section class="rules card"><div class="section-kicker">CONDICIONES DE INSCRIPCIÓN</div><h2>Reserva responsable para todos</h2><div class="rule-grid"><div><b>1</b><span>Un código deportivo solo puede participar <strong>una vez por día</strong>.</span></div><div><b>2</b><span>No se permite inscribirse en <strong>dos días deportivos consecutivos</strong>.</span></div><div><b>3</b><span>{esc(cfg['label'])}: <strong>{cfg['min']} a {cfg['max']}</strong> alumnos por reserva.</span></div><div><b>4</b><span>Solo se aceptan códigos registrados en la base institucional.</span></div></div></section>'''
    return f'''<section class="rules card lab-rules"><div class="section-kicker">USO DEL ESPACIO</div><h2>Una computadora por alumno</h2><div class="rule-grid"><div><b>1</b><span>Ingresa tu <strong>código de alumno</strong> para registrar tu computadora.</span></div><div><b>2</b><span>El ambiente está disponible <strong>de lunes a viernes</strong>.</span></div><div><b>3</b><span>Horario general: <strong>{SEAT_HOURS_LABEL}</strong>.</span></div><div><b>4</b><span>{esc(cfg['label'])}: <strong>{cfg['capacity']} computadoras</strong> en el espacio {esc(cfg['room'])}.</span></div></div></section>'''


def current_week_table(activity):
    cfg = ACTIVITIES[activity]
    ws = week_start_from().isoformat()

    # Laboratorios y Cutting ya no se dividen por día/hora: cada ambiente tiene
    # un único aforo visual para toda la semana, disponible de 9 a. m. a 10 p. m.
    if cfg['kind'] == 'seat':
        with db() as con:
            used = seat_used(con, ws, activity)
        remaining = max(0, cfg['capacity'] - used)
        admin_status, admin_reason = seat_admin_status(activity)
        if admin_status != 'available':
            status_label, status_icon = SEAT_STATUS_LABELS[admin_status]
            reason = esc(admin_reason or ('Ambiente temporalmente cerrado.' if admin_status == 'closed' else 'Ambiente en mantenimiento.'))
            return f'''<section class="seat-availability-banner seat-banner-{admin_status}">
                <div class="seat-availability-icon">{status_icon}</div>
                <div><span class="section-kicker">ESTADO DEL AMBIENTE</span><h2>{esc(status_label)}</h2><p>{reason}</p></div>
                <div class="seat-availability-state state-{admin_status}"><b>{remaining}</b><span>PUESTOS SIN OCUPAR</span><small>{used} ocupados de {cfg['capacity']}</small></div>
            </section><span class="btn disabled-seat-btn">{status_icon} {esc(status_label)}</span>{seat_map_html(activity)}'''
        action = '<span class="btn disabled-seat-btn">Aforo completo</span>' if remaining <= 0 else f'<a class="btn seat-main-action" href="/reservar?activity={quote(activity)}">Registrar una computadora</a>'
        return f'''<section class="seat-availability-banner">
            <div class="seat-availability-icon">🕘</div>
            <div><span class="section-kicker">DISPONIBILIDAD GENERAL</span><h2>Disponible de lunes a viernes</h2><p><strong>{SEAT_HOURS_LABEL}</strong></p></div>
            <div class="seat-availability-state"><b>{remaining}</b><span>COMPUTADORAS DISPONIBLES</span><small>{used} reservados de {cfg['capacity']}</small></div>
        </section>{action}{seat_map_html(activity)}'''

    with db() as con:
        res = con.execute("SELECT * FROM reservations WHERE week_start=? AND status='ACTIVA' AND sport IN ('futbol','voley')", (ws,)).fetchall()
        closed = con.execute('SELECT * FROM activity_closed_slots WHERE week_start=? AND activity=?', (ws, activity)).fetchall()
    occupied = {(r['day'], r['slot']): r for r in res}
    closedmap = {(c['day'], c['slot']): c for c in closed}
    rows_html = ''
    for slot in slots_for(activity):
        tds = ''
        for day in DAYS:
            if (day, slot) in closedmap:
                raw_reason = closedmap[(day, slot)]['reason'] or 'Horario cerrado por administración'
                reason = esc(raw_reason)
                closed_label = '⚙ Mantenimiento' if 'manten' in raw_reason.lower() else '🔒 Cerrado'
                cell = f'<span class="badge closed" title="{reason}"><span class="badge-label">{closed_label}</span></span>'
            elif (day, slot) in occupied:
                r = occupied[(day, slot)]
                cell = f'<span class="badge busy"><span class="badge-label">● Reservado</span><small>{esc(activity_label(r["sport"]))}</small></span>'
            else:
                cell = f'<a class="badge free" href="/reservar?activity={quote(activity)}&day={quote(day)}&slot={quote(slot)}" title="Seleccionar horario disponible"><span class="badge-label">✓ Disponible</span></a>'
            tds += f'<td>{cell}</td>'
        rows_html += f'<tr><th>{slot}</th>{tds}</tr>'
    legend = '<div class="availability-legend"><span class="legend-item legend-free"><i></i>Disponible</span><span class="legend-item legend-busy"><i></i>Reservado</span><span class="legend-item legend-closed"><i></i>Cerrado / mantenimiento</span></div>'
    return legend + f'<div class="table-wrap availability-table"><table class="week"><tr><th>Hora</th>' + ''.join(f'<th>{d}</th>' for d in DAYS) + f'</tr>{rows_html}</table></div>'


def seat_used(con, ws, activity, day=None, slot=None):
    # Total de usuarios activos del ambiente en la semana, sin fraccionarlo por horarios.
    row = con.execute('''SELECT COUNT(rs.code) c FROM reservations r
        JOIN reservation_students rs ON rs.reservation_id=r.id
        WHERE r.week_start=? AND r.sport=? AND r.status='ACTIVA' ''',
        (ws, activity)).fetchone()
    return int(row['c'] if row else 0)


def seat_people(con, ws, activity, day=None, slot=None):
    return con.execute('''SELECT rs.code,rs.name,r.id reservation_id
        FROM reservations r JOIN reservation_students rs ON rs.reservation_id=r.id
        WHERE r.week_start=? AND r.sport=? AND r.status='ACTIVA'
        ORDER BY r.id,rs.name''', (ws, activity)).fetchall()


def seat_icon_html(activity):
    if activity == 'diseno':
        return '<span class="computer-icon cutting-icon"><span class="cutting-main">✂️</span><span class="cutting-accent">📐</span></span>'
    return '<span class="computer-icon">🖥️</span>'


def seat_legend_html(activity):
    asset_name = 'Puesto CUT' if activity == 'diseno' else 'Computadora'
    asset_icon = seat_icon_html(activity)
    status, _ = seat_admin_status(activity)
    if status == 'available':
        free_icon, free_label, free_cls = '✅', 'Disponible', 'chip-free'
    else:
        free_label, free_icon = SEAT_STATUS_LABELS[status]
        free_cls = f'chip-{status}'
    return f'''<div class="seat-legend"><span class="seat-legend-item"><span class="seat-legend-chip {free_cls}"><span class="seat-status-icon">{free_icon}</span>{esc(free_label)}</span></span><span class="seat-legend-item"><span class="seat-legend-chip chip-occupied"><span class="seat-status-icon">👉</span>Ocupado</span></span><span class="seat-legend-item seat-legend-asset">{asset_icon}<b>{asset_name}</b></span></div>'''


def seat_map_html(activity, day=None, slot=None, compact=False):
    cfg = ACTIVITIES[activity]
    if cfg.get('kind') != 'seat':
        return ''
    ws = week_start_from().isoformat()
    with db() as con:
        people = seat_people(con, ws, activity)
    assigned = list(people)[:cfg['capacity']]
    seats = []
    asset_icon = seat_icon_html(activity)
    admin_status, _ = seat_admin_status(activity)
    legend = seat_legend_html(activity)
    seat_prefix = 'CUT' if activity == 'diseno' else 'PC'
    if admin_status == 'available':
        free_icon, free_label, free_status_cls, placeholder = '✅', 'Disponible', 'status-free-seat', 'Sin registrar'
    else:
        free_label, free_icon = SEAT_STATUS_LABELS[admin_status]
        free_status_cls = f'status-{admin_status}-seat'
        placeholder = 'No admite reservas'
    for idx in range(cfg['capacity']):
        n = idx + 1
        if idx < len(assigned):
            person = assigned[idx]
            seats.append(f'''<div class="computer-seat occupied">{asset_icon}<b>{seat_prefix}-{n:02d}</b><div class="seat-status status-occupied-seat"><span class="seat-status-icon">👉</span><span class="seat-status-text">Ocupado</span></div><strong class="seat-student-name">{esc(person['name'])}</strong><small class="seat-student-code">{esc(person['code'])}</small></div>''')
        else:
            seats.append(f'''<div class="computer-seat free seat-free-{admin_status}">{asset_icon}<b>{seat_prefix}-{n:02d}</b><div class="seat-status {free_status_cls}"><span class="seat-status-icon">{free_icon}</span><span class="seat-status-text">{esc(free_label)}</span></div><small class="seat-student-placeholder">{esc(placeholder)}</small></div>''')
    used = len(assigned)
    remaining = max(0, cfg['capacity'] - used)
    cls = 'computer-map compact' if compact else 'computer-map'
    map_title = 'MAPA DEL AULA CUTTING' if activity == 'diseno' else 'MAPA DE COMPUTADORAS'
    availability_copy = f'<strong>{remaining} disponibles</strong> de {cfg["capacity"]}' if admin_status == 'available' else f'<strong>{remaining} puestos sin ocupar</strong> de {cfg["capacity"]}'
    return f'''<section class="{cls}"><div class="computer-map-head"><div><span class="section-kicker">{map_title}</span><h2>{esc(cfg['label'])} · Espacio {esc(cfg['room'])}</h2><p>{availability_copy} · atención habitual de {SEAT_HOURS_LABEL}. Los puestos ocupados muestran el nombre del alumno.</p>{legend}</div></div><div class="computer-grid">{''.join(seats)}</div></section>'''


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
            locked = '' if is_open_now() else '<div class="alert">⏰ Las inscripciones se habilitan desde las 8:00 a. m. Puedes revisar todos los espacios mientras tanto.</div>'
            body = f'''<section class="viva-hero viva-home-hero">
                <div class="hero-side hero-side-left" aria-hidden="true">
                    <span class="hero-float hero-float-football">⚽</span>
                    <span class="hero-float hero-float-volley">🏐</span>
                    <i class="hero-ring hero-ring-left"></i>
                </div>
                <div class="viva-hero-copy hero-center-copy">
                    <div class="viva-flag hero-flag">VIVA</div>
                    <p class="viva-script">Vive tu campus.</p>
                    <h1>¿Qué quieres hacer hoy?</h1>
                    <div class="hero-mini-line"><span>Reserva</span><i>•</i><span>Participa</span><i>•</i><strong>VIVE</strong></div>
                </div>
                <div class="hero-side hero-side-right" aria-hidden="true">
                    <span class="hero-float hero-float-mac">🖥️</span>
                    <span class="hero-float hero-float-windows">▦</span>
                    <span class="hero-float hero-float-design">✦</span>
                    <i class="hero-ring hero-ring-right"></i>
                </div>
            </section>{locked}<section class="experience-section home-experiences"><div class="experience-heading"><span>ELIGE TU EXPERIENCIA</span><b>Selecciona la actividad de tu preferencia</b></div>{activity_cards_html()}</section><section class="viva-promise"><b>Reserva. Participa. VIVE.</b><span>Elige tu espacio: deportes por horario y laboratorios disponibles de lunes a viernes, de 9 a. m. a 10 p. m.</span></section>'''
            return self.send(200, html_page('VIVA · Vive tu campus', body, self.require_admin()))

        if p.path == '/semana':
            q = parse_qs(p.query)
            activity = q.get('activity', ['futbol'])[0]
            if activity not in ACTIVITIES:
                activity = 'futbol'
            cfg = ACTIVITIES[activity]
            room_copy = f' · Espacio {esc(cfg["room"])}' if cfg['room'] else ''
            room_focus = room_focus_html(cfg)
            global_status = seat_status_badge(activity) if cfg['kind'] == 'seat' else ''
            if cfg['kind'] == 'seat':
                admin_status, admin_reason = seat_admin_status(activity)
                if admin_status == 'available':
                    detail_copy = f'Disponible de lunes a viernes, de {SEAT_HOURS_LABEL}{room_copy}.'
                else:
                    status_label, _ = SEAT_STATUS_LABELS[admin_status]
                    detail_copy = f'{status_label}{room_copy}.' + (f' {esc(admin_reason)}' if admin_reason else '')
            else:
                detail_copy = f'Selecciona un horario disponible de lunes a viernes{room_copy}.'
            body = f'''<div class="page-title activity-page-title"><span class="activity-title-icon">{esc(cfg['icon'])}</span><div class="activity-title-copy"><span class="section-kicker">DISPONIBILIDAD · {esc(cfg['label']).upper()}</span><h1>{esc(cfg['label'])}</h1><p>{detail_copy}</p>{global_status}</div>{room_focus}</div>{activity_selector(activity)}{current_week_table(activity)}{reservation_rules_html(activity)}'''
            return self.send(200, html_page(f'{cfg["label"]} · VIVA', body, self.require_admin()))

        if p.path == '/puestos':
            q = parse_qs(p.query)
            activity = q.get('activity', ['imac'])[0]
            if activity not in ACTIVITIES or ACTIVITIES[activity].get('kind') != 'seat':
                activity = 'imac'
            return self.redirect('/semana?activity=' + quote(activity))

        if p.path == '/reservar':
            q = parse_qs(p.query)
            activity = q.get('activity', ['futbol'])[0]
            day = q.get('day', [''])[0]
            slot = q.get('slot', [''])[0]
            if activity not in ACTIVITIES:
                return self.redirect('/semana?activity=futbol')
            cfg = ACTIVITIES[activity]
            if cfg['kind'] == 'seat':
                admin_status, admin_reason = seat_admin_status(activity)
                if admin_status != 'available':
                    status_label, status_icon = SEAT_STATUS_LABELS[admin_status]
                    reason = esc(admin_reason or 'Este ambiente no admite nuevas reservas por el momento.')
                    body = f'<div class="alert error"><b>{status_icon} {esc(status_label)}</b><br>{reason}</div><a class="btn" href="/semana?activity={quote(activity)}">Volver al ambiente</a>'
                    return self.send(200, html_page(f'{status_label} · VIVA', body, self.require_admin()))
                day, slot = SEAT_DAY, SEAT_SLOT
            elif day not in DAYS or slot not in slots_for(activity):
                return self.redirect('/semana?activity=' + quote(activity))
            ws = week_start_from().isoformat()
            with db() as con:
                if cfg['kind'] == 'team':
                    closed = con.execute('SELECT reason FROM activity_closed_slots WHERE week_start=? AND activity=? AND day=? AND slot=?', (ws, activity, day, slot)).fetchone()
                    occupied = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA' AND sport IN ('futbol','voley')", (ws, day, slot)).fetchone()
                    remaining = None
                else:
                    closed = None
                    occupied = None
                    remaining = cfg['capacity'] - seat_used(con, ws, activity)
            if occupied or closed or (remaining is not None and remaining <= 0):
                return self.send(200, html_page('Horario no disponible', f'<div class="alert error"><b>Ese horario ya no está disponible.</b><br>Actualiza la disponibilidad de {esc(cfg["label"])} y elige otro horario.</div><a class="btn" href="/semana?activity={quote(activity)}">Volver a disponibilidad</a>', self.require_admin()))
            disabled = '' if is_open_now() else 'disabled'
            msg = '' if is_open_now() else '<div class="alert">Aún no se puede reservar. Las inscripciones se habilitan desde las 8:00 a. m.</div>'
            if cfg['kind'] == 'team':
                fields = ''.join(f'<div class="code-row"><label>Código {i}{" *" if i <= cfg["min"] else ""}</label><input name="code{i}" class="student-code" autocomplete="off" placeholder="Ej. código institucional"><small></small></div>' for i in range(1, cfg['max'] + 1))
                note = f'<div class="inline-note">{esc(cfg["label"])} requiere entre <b>{cfg["min"]} y {cfg["max"]} alumnos</b>. Se mantienen las reglas deportivas de una inscripción por día y no días consecutivos.</div>'
            else:
                fields = '<div class="code-row single-code"><label>Código de alumno *</label><input name="code1" class="student-code" autocomplete="off" placeholder="Ingresa tu código institucional" required><small></small></div>'
                note = f'<div class="inline-note lab-note"><b>{remaining} computadoras disponibles de {cfg["capacity"]}</b>. Atención de lunes a viernes, de {SEAT_HOURS_LABEL}. No necesitas elegir un horario.</div>'
            room_focus = room_focus_html(cfg, compact=True)
            map_preview = seat_map_html(activity, day, slot, compact=True) if cfg['kind'] == 'seat' else ''
            reserve_when = (f'Lunes a viernes · {SEAT_HOURS_LABEL} · Espacio {esc(cfg["room"])}' if cfg['kind'] == 'seat' else f'{esc(day)} · {esc(slot)} · Espacio {esc(cfg["room"])}')
            back_label = '← Volver a computadoras' if cfg['kind'] == 'seat' else '← Elegir otro horario'
            body = f'''<div class="page-title reserve-title"><span class="activity-title-icon">{esc(cfg['icon'])}</span><div class="activity-title-copy"><span class="section-kicker">NUEVA RESERVA · VIVA</span><h1>{esc(cfg['label'])}</h1><p>{reserve_when}</p></div>{room_focus}</div>{msg}<form class="card reserve-card" method="post" action="/reservar" data-mode="{cfg['kind']}"><input type="hidden" name="activity" value="{esc(activity)}"><input type="hidden" name="day" value="{esc(day)}"><input type="hidden" name="slot" value="{esc(slot)}">{note}<div id="codes" class="grid-codes {'one-column' if cfg['kind']=='seat' else ''}">{fields}</div><button class="btn wide viva-submit" {disabled}>Confirmar reserva</button><a class="form-back" href="/semana?activity={quote(activity)}">{back_label}</a></form>{map_preview}'''
            return self.send(200, html_page('Nueva reserva · VIVA', body, self.require_admin()))

        if p.path == '/admin':
            if not self.require_admin():
                body = '<form class="login card" method="post" action="/login"><div class="admin-icon viva-admin-icon">V</div><span class="section-kicker">VIVA · ACCESO RESTRINGIDO</span><h1>Panel administrador</h1><p class="muted">Gestiona deportes, laboratorios, aulas, aforos y horarios.</p><label>Usuario</label><input name="user" autocomplete="username" placeholder="Usuario" required><label>Contraseña</label><input name="password" type="password" autocomplete="current-password" placeholder="Contraseña" required><button class="btn wide">Ingresar</button></form>'
                return self.send(200, html_page('Administrador · VIVA', body))
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
            reservas = [r for r in reservas if (r['day'] in DAYS) or (r['sport'] in ACTIVITIES and ACTIVITIES[r['sport']]['kind'] == 'seat')]
            active = [r for r in reservas if r['status'] == 'ACTIVA']
            cancelled = [r for r in reservas if r['status'] == 'CANCELADA']
            closed_rows = [c for c in con.execute('SELECT * FROM activity_closed_slots WHERE week_start=? ORDER BY day,slot', (ws,)).fetchall() if c['day'] in DAYS and c['activity'] in SPORT_KEYS]
            participants = con.execute('''SELECT rs.reservation_id,rs.code,rs.name FROM reservation_students rs
                JOIN reservations r ON r.id=rs.reservation_id WHERE r.week_start=? ORDER BY rs.name''', (ws,)).fetchall()
        pmap = {}
        for p in participants:
            pmap.setdefault(p['reservation_id'], []).append(p)

        day_counts = {d: 0 for d in DAYS}
        hour_counts = {s.split('-')[0]: 0 for s in ALL_TIME_SLOTS}
        activity_counts = {cfg['label']: 0 for cfg in ACTIVITIES.values()}
        activity_participants = {key: 0 for key in ACTIVITIES}
        for r in active:
            if r['day'] in day_counts:
                day_counts[r['day']] += 1
            hour = r['slot'].split('-')[0]
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
            key = r['sport']
            if key in ACTIVITIES:
                activity_counts[ACTIVITIES[key]['label']] += 1
                activity_participants[key] += int(r['participant_count'] or 0)
        active_participants = sum(int(r['participant_count'] or 0) for r in active)

        cards = f'''<div class="stats"><div><span class="stat-icon">👥</span><b>{total_students}</b><small>Alumnos en base</small></div><div><span class="stat-icon">✅</span><b>{len(active)}</b><small>Reservas activas</small></div><div><span class="stat-icon">🎟️</span><b>{active_participants}</b><small>Cupos / participantes</small></div><div><span class="stat-icon">✕</span><b>{len(cancelled)}</b><small>Canceladas</small></div></div>'''

        usage_cards = ''
        for key, cfg in ACTIVITIES.items():
            if cfg['kind'] == 'seat':
                metric = f'{activity_participants[key]} cupos usados'
                admin_status, admin_reason = seat_admin_status(key)
                status_label, status_icon = SEAT_STATUS_LABELS[admin_status]
                reason_text = f' · {admin_reason}' if admin_reason else ''
                sub = f'{status_icon} {status_label}{reason_text} · Aforo {cfg["capacity"]} · Espacio {cfg["room"]}'
            else:
                count = sum(1 for r in active if r['sport'] == key)
                metric = f'{count} reservas'
                sub = f'{cfg["min"]} a {cfg["max"]} alumnos · {cfg["room"]}'
            room_badge = f'<em class="resource-room">{esc(cfg["room"])}</em>' if cfg['kind'] == 'seat' else ''
            usage_cards += f'<div class="resource-card"><span>{esc(cfg["icon"])}</span><div><b>{esc(cfg["label"])}</b>{room_badge}<strong>{esc(metric)}</strong><small>{esc(sub)}</small></div></div>'

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
            cfg = ACTIVITIES.get(r['sport'], {'label': r['sport'].title(), 'icon': '•', 'room': '—', 'kind': 'team'})
            people_label = f'{r["participant_count"]} alumno' if int(r['participant_count'] or 0) == 1 else f'{r["participant_count"]} alumnos'
            rows += f'''<tr><td><b>R-{int(r['id']):05d}</b></td><td>{esc(r['day'])}<small>{esc(r['slot'])}</small></td><td><b>{esc(cfg['icon'])} {esc(cfg['label'])}</b><small>Espacio {esc(cfg['room'])}</small></td><td><span class="status-pill {status_class}">{('Reservado' if r['status'] == 'ACTIVA' else esc(r['status'].title()))}</span></td><td>{esc(people_label)}<details><summary>Ver alumno(s)</summary><ul class="student-list">{students_html}</ul></details></td><td>{esc(r['created_at'])}</td><td>{action}</td></tr>'''

        closed_html = ''.join(f'''<tr><td>{esc(ACTIVITIES[c['activity']]['icon'])} {esc(ACTIVITIES[c['activity']]['label'])}</td><td>{esc(c['day'])}</td><td>{esc(c['slot'])}</td><td>{esc(c['reason'] or 'Sin motivo')}</td><td><form method="post" action="/open-slot"><input type="hidden" name="activity" value="{esc(c['activity'])}"><input type="hidden" name="day" value="{esc(c['day'])}"><input type="hidden" name="slot" value="{esc(c['slot'])}"><button class="secondary small-btn">Reabrir</button></form></td></tr>''' for c in closed_rows)
        day_options = ''.join(f'<option value="{d}">{d}</option>' for d in DAYS)
        activity_options = ''.join(f'<option value="{key}">{esc(ACTIVITIES[key]["label"])} · {esc(ACTIVITIES[key]["room"])}</option>' for key in SPORT_KEYS)
        slot_options = ''.join(f'<option value="{s}">{s}</option>' for s in slots_for('futbol'))
        activity_meta = {k: {'slots': slots_for(k), 'label': ACTIVITIES[k]['label']} for k in SPORT_KEYS}
        stats_script = f'''<script>window.DASH_DATA={{days:{json.dumps(day_counts, ensure_ascii=False)},hours:{json.dumps(hour_counts, ensure_ascii=False)},activities:{json.dumps(activity_counts, ensure_ascii=False)}}};window.ACTIVITY_META={json.dumps(activity_meta, ensure_ascii=False)};</script>'''
        room_editor = f'''<section class="card room-editor"><div class="section-head compact"><div><span class="section-kicker">CONFIGURACIÓN DE AMBIENTES</span><h2>Editar números de salones</h2></div><span class="muted">Los cambios se guardan permanentemente</span></div><p class="muted">Modifica 105, 210 y 510 cuando cambien los salones. Puedes usar números o códigos como A-105.</p><form method="post" action="/update-spaces" class="room-edit-grid"><label>🖥️ Laboratorio Mac<input name="room_imac" value="{esc(ACTIVITIES['imac']['room'])}" maxlength="30" required></label><label>🖥️ Laboratorio Windows<input name="room_windows" value="{esc(ACTIVITIES['windows']['room'])}" maxlength="30" required></label><label>✂️ Aula de Cutting<input name="room_diseno" value="{esc(ACTIVITIES['diseno']['room'])}" maxlength="30" required></label><button class="btn room-save">Guardar salones</button></form></section>'''

        seat_status_cards = ''
        for seat_key in ('imac', 'windows', 'diseno'):
            seat_cfg = ACTIVITIES[seat_key]
            current_status, current_reason = seat_admin_status(seat_key)
            status_label, status_icon = SEAT_STATUS_LABELS[current_status]
            options = ''.join(f'<option value="{value}" {"selected" if value == current_status else ""}>{icon} {label}</option>' for value, (label, icon) in SEAT_STATUS_LABELS.items())
            seat_status_cards += f'''<form method="post" action="/update-seat-status" class="seat-admin-card status-{current_status}"><input type="hidden" name="activity" value="{seat_key}"><div class="seat-admin-card-head"><span class="seat-admin-icon">{esc(seat_cfg['icon'])}</span><div><span>{esc(seat_cfg['label'])}</span><b>Espacio {esc(seat_cfg['room'])}</b></div><strong>{status_icon} {esc(status_label)}</strong></div><label>Estado del ambiente<select name="status" required>{options}</select></label><label>Motivo / aviso para alumnos<input name="reason" maxlength="180" value="{esc(current_reason)}" placeholder="Ej. mantenimiento de equipos"></label><button class="btn wide">Guardar estado</button></form>'''
        seat_status_editor = f'''<section class="card seat-admin-section"><div class="section-head compact"><div><span class="section-kicker">CONTROL DE LABORATORIOS Y CUTTING</span><h2>Abrir, cerrar o poner en mantenimiento</h2></div><span class="muted">El cambio bloquea o habilita nuevas reservas</span></div><p class="muted">Las reservas ya registradas se conservan. Cuando un ambiente está Cerrado o En mantenimiento, los alumnos pueden ver su estado pero no registrar nuevos puestos.</p><div class="seat-admin-grid">{seat_status_cards}</div></section>'''

        body = f'''<div class="admin-heading"><div><span class="section-kicker">VIVA · ADMINISTRACIÓN · {esc(db_label())}</span><h1>Control del campus</h1><p>Semana del {esc(ws)} · deportes, laboratorios y aulas en un solo panel.</p></div><a class="btn small" href="/export.csv">Exportar registros CSV</a></div>{msg_html}{cards}<section class="resource-overview"><div class="section-head compact"><div><span class="section-kicker">ESPACIOS</span><h2>Estado de uso</h2></div></div><div class="resource-grid">{usage_cards}</div></section>{room_editor}{seat_status_editor}<section class="dashboard-grid"><div class="card chart-card"><div class="chart-title"><span>Uso por día</span><b>Reservas semanales</b></div><canvas id="chartDays" height="220"></canvas></div><div class="card chart-card"><div class="chart-title"><span>Uso por hora</span><b>Horas más solicitadas</b></div><canvas id="chartHours" height="220"></canvas></div></section><section class="dashboard-grid"><div class="card"><span class="section-kicker">GESTIÓN DE HORARIOS</span><h2>Cerrar un horario</h2><p class="muted">Esta gestión aplica solo a Fútbol y Vóley. Mac, Windows y Cutting usan disponibilidad general de lunes a viernes, de 9 a. m. a 10 p. m.</p><form method="post" action="/close-slot" class="form-grid"><label class="full">Actividad / espacio<select name="activity" id="admin-activity" required>{activity_options}</select></label><label>Día<select name="day" required>{day_options}</select></label><label>Horario<select name="slot" id="admin-slot" required>{slot_options}</select></label><label class="full">Motivo<input name="reason" placeholder="Ej. mantenimiento, actividad institucional"></label><button class="btn full">Cerrar horario</button></form></div><div class="card"><span class="section-kicker">DISTRIBUCIÓN</span><h2>Reservas por actividad</h2><canvas id="chartActivities" height="220"></canvas></div></section><section class="card"><div class="section-head compact"><div><span class="section-kicker">REGISTROS</span><h2>Reservas de esta semana</h2></div><span class="muted">{len(reservas)} registros</span></div><div class="table-wrap flat"><table class="admin-table"><tr><th>Reserva</th><th>Día / hora</th><th>Actividad / espacio</th><th>Estado</th><th>Alumno(s)</th><th>Creada</th><th>Acción</th></tr>{rows or '<tr><td colspan="7">Sin reservas todavía.</td></tr>'}</table></div></section><section class="card"><div class="section-head compact"><div><span class="section-kicker">BLOQUEOS</span><h2>Horarios cerrados</h2></div><span class="muted">{len(closed_rows)} cerrados</span></div><div class="table-wrap flat"><table><tr><th>Actividad</th><th>Día</th><th>Hora</th><th>Motivo</th><th>Acción</th></tr>{closed_html or '<tr><td colspan="5">No hay horarios cerrados.</td></tr>'}</table></div></section><section class="card"><span class="section-kicker">BASE DE ALUMNOS</span><h2>Actualizar padrón</h2><form method="post" action="/upload" enctype="multipart/form-data" class="upload-row"><input type="file" name="file" accept=".xlsx,.csv" required><button class="btn">Subir base</button></form><p class="muted">Acepta Excel .xlsx o CSV con columnas NombreCompleto, DNI y Código.</p></section>{stats_script}'''
        return self.send(200, html_page('Panel administrador · VIVA', body, True))

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
                return self.send(200, html_page('Reservas cerradas', '<div class="alert">Las reservas se habilitan desde las 8:00 a. m.</div><a class="btn" href="/">Volver</a>'))
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

        if p.path == '/update-spaces':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            updates = {}
            for activity, setting_key in ROOM_SETTING_KEYS.items():
                value = data.get(setting_key, [''])[0].strip()[:30]
                if not value:
                    return self.redirect('/admin?err=' + quote('Todos los salones deben tener un número o código.'))
                updates[activity] = (setting_key, value)
            with db() as con:
                for activity, (setting_key, value) in updates.items():
                    con.execute('''INSERT INTO settings(key,value) VALUES(?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (setting_key, value))
                    ACTIVITIES[activity]['room'] = value
            return self.redirect('/admin?msg=' + quote('Salones actualizados correctamente.'))

        if p.path == '/update-seat-status':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            activity = data.get('activity', [''])[0]
            status = data.get('status', [''])[0]
            reason = data.get('reason', [''])[0].strip()[:180]
            if activity not in SEAT_STATUS_KEYS or status not in SEAT_STATUS_LABELS:
                return self.redirect('/admin?err=' + quote('Estado o ambiente inválido.'))
            status_key, reason_key = SEAT_STATUS_KEYS[activity]
            with db() as con:
                con.execute('''INSERT INTO settings(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (status_key, status))
                con.execute('''INSERT INTO settings(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (reason_key, reason))
            label, icon = SEAT_STATUS_LABELS[status]
            return self.redirect('/admin?msg=' + quote(f'{activity_label(activity)} ahora está: {icon} {label}.'))

        if p.path == '/close-slot':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            activity = data.get('activity', [''])[0]
            day = data.get('day', [''])[0]
            slot = data.get('slot', [''])[0]
            reason = data.get('reason', [''])[0].strip()[:180]
            if activity not in SPORT_KEYS or day not in DAYS or slot not in slots_for(activity):
                return self.redirect('/admin?err=' + quote('Actividad, día u horario inválido.'))
            ws = week_start_from().isoformat()
            with db() as con:
                if ACTIVITIES[activity]['kind'] == 'team':
                    active = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA' AND sport=?", (ws, day, slot, activity)).fetchone()
                else:
                    active = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA' AND sport=?", (ws, day, slot, activity)).fetchone()
                if active:
                    return self.redirect('/admin?err=' + quote('Ese horario tiene reservas activas. Cancélalas antes de cerrar el horario.'))
                con.execute('''INSERT INTO activity_closed_slots(week_start,activity,day,slot,reason) VALUES(?,?,?,?,?)
                    ON CONFLICT(week_start,activity,day,slot) DO UPDATE SET reason=excluded.reason''', (ws, activity, day, slot, reason or 'Cerrado por administración'))
            return self.redirect('/admin?msg=' + quote(f'{activity_label(activity)} · {day} {slot} cerrado correctamente.'))

        if p.path == '/open-slot':
            if not self.require_admin():
                return self.redirect('/admin')
            data = parse_qs(self.read_post().decode('utf-8', errors='ignore'))
            activity = data.get('activity', [''])[0]
            day = data.get('day', [''])[0]
            slot = data.get('slot', [''])[0]
            ws = week_start_from().isoformat()
            with db() as con:
                con.execute('DELETE FROM activity_closed_slots WHERE week_start=? AND activity=? AND day=? AND slot=?', (ws, activity, day, slot))
            return self.redirect('/admin?msg=' + quote(f'{activity_label(activity)} · {day} {slot} volvió a estar disponible.'))

        if p.path == '/upload':
            if not self.require_admin():
                return self.redirect('/admin')
            return self.handle_upload()

        return self.send(404, 'No encontrado')

    def create_reservation(self, data):
        activity = data.get('activity', data.get('sport', ['']))[0]
        day = data.get('day', [''])[0]
        slot = data.get('slot', [''])[0]
        if activity not in ACTIVITIES:
            return self.send(400, html_page('Datos inválidos', '<div class="alert error">Datos de reserva inválidos.</div><a class="btn" href="/">Volver</a>'))
        cfg = ACTIVITIES[activity]
        if cfg['kind'] == 'seat':
            admin_status, admin_reason = seat_admin_status(activity)
            if admin_status != 'available':
                status_label, status_icon = SEAT_STATUS_LABELS[admin_status]
                reason = esc(admin_reason or 'Este ambiente no admite nuevas reservas por el momento.')
                return self.send(200, html_page(f'{status_label} · VIVA', f'<div class="alert error"><b>{status_icon} {esc(status_label)}</b><br>{reason}</div><a class="btn" href="/semana?activity={quote(activity)}">Volver al ambiente</a>', self.require_admin()))
            day, slot = SEAT_DAY, SEAT_SLOT
        elif day not in DAYS or slot not in slots_for(activity):
            return self.send(400, html_page('Datos inválidos', '<div class="alert error">Datos de reserva inválidos.</div><a class="btn" href="/">Volver</a>'))
        max_fields = cfg.get('max', 1)
        codes = [data.get(f'code{i}', [''])[0].strip().upper() for i in range(1, max_fields + 1)]
        codes = [c for c in codes if c]
        errors = []

        if cfg['kind'] == 'team':
            if len(codes) < cfg['min']:
                errors.append(f'Para {cfg["label"]} se requieren mínimo {cfg["min"]} alumnos.')
            if len(codes) > cfg['max']:
                errors.append(f'Para {cfg["label"]} se permiten máximo {cfg["max"]} alumnos.')
        else:
            if len(codes) != 1:
                errors.append('Ingresa un código de alumno para reservar un cupo.')
        if len(codes) != len(set(codes)):
            errors.append('No se permiten códigos repetidos dentro de la misma reserva.')

        ws = week_start_from().isoformat()
        with RESERVATION_LOCK:
            with db() as con:
                closed = None
                if cfg['kind'] == 'team':
                    closed = con.execute('SELECT reason FROM activity_closed_slots WHERE week_start=? AND activity=? AND day=? AND slot=?', (ws, activity, day, slot)).fetchone()
                    if closed:
                        errors.append('Ese horario fue cerrado por administración.')

                if cfg['kind'] == 'team':
                    existing = con.execute("SELECT id FROM reservations WHERE week_start=? AND day=? AND slot=? AND status='ACTIVA' AND sport IN ('futbol','voley')", (ws, day, slot)).fetchone()
                    if existing:
                        errors.append('Ese horario de la cancha ya está reservado.')
                else:
                    used = seat_used(con, ws, activity)
                    if used >= cfg['capacity']:
                        errors.append('Este ambiente ya alcanzó su aforo máximo de computadoras.')

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

                if codes and cfg['kind'] == 'team':
                    placeholders = ','.join('?' * len(codes))
                    usage = con.execute(f'''SELECT rs.code,r.day,r.slot FROM reservation_students rs
                        JOIN reservations r ON r.id=rs.reservation_id
                        WHERE r.week_start=? AND r.status='ACTIVA' AND r.sport IN ('futbol','voley') AND rs.code IN ({placeholders})''', [ws] + codes).fetchall()
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
                        errors.append(f'{c} · {nm}: ya tiene una inscripción deportiva activa el {day}.')
                    for c in sorted(consecutive):
                        nm = students[c]['name'] if c in students else ''
                        errors.append(f'{c} · {nm}: no puede inscribirse en dos días deportivos consecutivos.')

                if codes and cfg['kind'] == 'seat':
                    duplicate = con.execute('''SELECT r.id FROM reservations r JOIN reservation_students rs ON rs.reservation_id=r.id
                        WHERE r.week_start=? AND r.sport=? AND r.status='ACTIVA' AND rs.code=?''',
                        (ws, activity, codes[0])).fetchone()
                    if duplicate:
                        errors.append('Ese código ya tiene una computadora registrada en este espacio.')

                if errors:
                    unique_errors = list(dict.fromkeys(errors))
                    items = ''.join(f'<li>{esc(e)}</li>' for e in unique_errors)
                    return self.send(200, html_page('No se pudo reservar', f'<div class="alert error"><b>No se pudo confirmar la reserva.</b><ul>{items}</ul></div><a class="btn" href="/semana?activity={quote(activity)}">Elegir otro horario</a>'))

                created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    captain = codes[0] if codes else ''
                    if is_postgres():
                        rid = con.execute('''INSERT INTO reservations(week_start,day,slot,sport,captain_code,created_at)
                            VALUES(?,?,?,?,?,?) RETURNING id''', (ws, day, slot, activity, captain, created_at)).fetchone()['id']
                    else:
                        cur = con.execute('''INSERT INTO reservations(week_start,day,slot,sport,captain_code,created_at)
                            VALUES(?,?,?,?,?,?)''', (ws, day, slot, activity, captain, created_at))
                        rid = cur.lastrowid
                    for c in codes:
                        con.execute('INSERT INTO reservation_students(reservation_id,code,name) VALUES(?,?,?)', (rid, c, students[c]['name']))
                except Exception as exc:
                    con.con.rollback()
                    print('Error al crear reserva:', exc)
                    return self.send(200, html_page('Horario no disponible', f'<div class="alert error"><b>La reserva no pudo guardarse.</b><br>Revisa nuevamente la disponibilidad.</div><a class="btn" href="/semana?activity={quote(activity)}">Actualizar disponibilidad</a>'))

        names = ''.join(f'<li><b>{esc(c)}</b> · {esc(students[c]["name"])}</li>' for c in codes)
        remaining_copy = ''
        if cfg['kind'] == 'seat':
            with db() as con:
                remaining = max(0, cfg['capacity'] - seat_used(con, ws, activity))
            remaining_copy = f'<div class="remaining-chip">{remaining} computadoras disponibles</div>'
        success_space = f'<div class="success-space"><span>ESPACIO</span><strong>{esc(cfg["room"])}</strong></div>' if cfg['kind'] == 'seat' else f'<p class="muted">{esc(cfg["room"])}</p>'
        success_when = f'Lunes a viernes · {SEAT_HOURS_LABEL}' if cfg['kind'] == 'seat' else f'{esc(day)} · {esc(slot)}'
        return self.send(200, html_page('Reserva confirmada · VIVA', f'''<section class="success reservation-success viva-success"><div class="success-check">✓</div><div class="viva-flag success-flag">VIVA</div><p class="viva-script success-script">Vive tu campus.</p><h1>¡Tu reserva está lista!</h1><p class="reservation-summary">{esc(cfg['icon'])} {esc(cfg['label'])} · {success_when}</p>{success_space}<div class="reservation-code">R-{int(rid):05d}</div>{remaining_copy}<details><summary>Ver alumno(s)</summary><ul>{names}</ul></details><a class="btn" href="/semana?activity={quote(activity)}">Volver a disponibilidad</a></section>'''))

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
        w.writerow(['Reserva', 'Semana', 'Día', 'Horario', 'Actividad', 'Espacio', 'Estado', 'Código', 'Alumno', 'Creado', 'Cancelado', 'Cancelado por'])
        with db() as con:
            rows = con.execute('''SELECT r.id,r.week_start,r.day,r.slot,r.sport,r.status,rs.code,rs.name,r.created_at,r.cancelled_at,r.cancelled_by
                FROM reservations r JOIN reservation_students rs ON r.id=rs.reservation_id
                WHERE r.week_start=? ORDER BY r.id,rs.name''', (ws,)).fetchall()
        for r in rows:
            cfg = ACTIVITIES.get(r['sport'], {'label': r['sport'].title(), 'room': ''})
            w.writerow([r['id'], r['week_start'], r['day'], r['slot'], cfg['label'], cfg['room'], r['status'], r['code'], r['name'], r['created_at'], r['cancelled_at'] or '', r['cancelled_by'] or ''])
        return self.send(200, out.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="viva_reservas_semana.csv"'})


def main():
    init_db()
    print(f'✅ VIVA listo en http://127.0.0.1:{PORT} · Base: {db_label()}')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
