import mysql.connector
from functools import wraps
from dotenv import load_dotenv
from flask import request, session, redirect, url_for
import os

load_dotenv()


MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_ADDON_HOST'),
    'user': os.getenv('MYSQL_ADDON_USER'),
    'password': os.getenv('MYSQL_ADDON_PASSWORD'),
    'database': os.getenv('MYSQL_ADDON_DB'),
    'port': int(os.getenv('MYSQL_ADDON_PORT', 3306))
}

def get_db_connection():
    return mysql.connector.connect(**MYSQL_CONFIG)

def get_client_ip():
    """Safely extracts client IP address."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

def log_audit_event(username, ip_address, action):
    """Securely logs user actions and IPs using parameterized queries."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO audit_logs (username, ip_address, action) VALUES (%s, %s, %s)"
        cursor.execute(query, (username, ip_address, action))
        conn.commit()
        cursor.close()
    except mysql.connector.Error as e:
        print(f"[AUDIT ERROR] Could not log event: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

def is_ip_blocked(ip_address):
    """Dynamically checks if an IP has 5 or more failed logins in the last 15 minutes."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT COUNT(*) FROM audit_logs 
            WHERE ip_address = %s 
              AND action = 'LOGIN_FAILED' 
              AND timestamp >= (NOW() - INTERVAL 15 MINUTE)
        """
        cursor.execute(query, (ip_address,))
        result = cursor.fetchone()
        
        if result and result[0] >= 5:
            return True
    except mysql.connector.Error as e:
        print(f"[BLOCK CHECK ERROR]: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()
            
    return False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("SELECT DATABASE()")
print("Database:", cursor.fetchone())

cursor.execute("SHOW TABLES")
for table in cursor.fetchall():
    print(table)

conn.close()