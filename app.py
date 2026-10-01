from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from utils import get_db_connection, get_client_ip, log_audit_event, is_ip_blocked, login_required
from product import product_bp
from order import order_bp

app = Flask(__name__)
app.secret_key = 'super_secret_shopadmin_key_for_testing'

# Register Blueprints
app.register_blueprint(product_bp)
app.register_blueprint(order_bp)

# @app.before_request
# def check_blocked_ips():
#     client_ip = get_client_ip()
#     if is_ip_blocked(client_ip):
#         return "Your IP address has been temporarily blocked due to multiple failed login attempts.", 403

@app.route('/')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('product.products'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('product.products'))

    message = None
    query_executed = None
    client_ip = get_client_ip()

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        raw_query = f"select * FROM shop_users WHERE username = '{username}' AND password = '{password}' limit 1"
        query_executed = raw_query

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            user = None
            try:
                for result in cursor.execute(raw_query, multi=True):
                    if result.with_rows:
                        user = result.fetchone()
                        break
            except TypeError:
                cursor.execute(raw_query)
                user = cursor.fetchone()

            if user:
                log_audit_event(username, client_ip, 'LOGIN_SUCCESS')

                session['user_id'] = user[0]
                session['user'] = user[1]
                session['role'] = user[3]
                session['email'] = user[4]
                
                cursor.close()
                conn.close()
                return redirect(url_for('product.products'))
            else:
                log_audit_event(username, client_ip, 'LOGIN_FAILED')
                message = "Invalid credentials."

            cursor.close()
        except mysql.connector.Error as e:
            message = f"MySQL Error: {e}"
        except Exception as e:
            message = f"Error: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    return render_template('login.html', message=message, query=query_executed, ip=client_ip)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# USER PROFILE & ADDRESS MANAGEMENT ROUTE
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    message = None
    query_executed = None
    user_id = session.get('user_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Handle Profile Updates (First Name, Last Name, Contact, Email)
    if request.method == 'POST' and 'update_profile' in request.form:
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        contact = request.form.get('contact', '')
        email = request.form.get('email', '')

        raw_query = f"""
            UPDATE shop_users 
            SET first_name = '{first_name}', last_name = '{last_name}', contact = '{contact}', email = '{email}' 
            WHERE id = {user_id}
        """
        query_executed = raw_query

        try:
            cursor.execute(raw_query)
            conn.commit()
            message = "Profile updated successfully!"
            session['email'] = email
        except mysql.connector.Error as e:
            message = f"MySQL Error: {e}"

    # Handle Adding New Address
    elif request.method == 'POST' and 'add_address' in request.form:
        address = request.form.get('address', '')
        landmark = request.form.get('landmark', '')

        try:
            cursor.execute(
                "INSERT INTO Address (user_id, address, landmark) VALUES (%s, %s, %s)",
                (user_id, address, landmark)
            )
            conn.commit()
            message = "Address added successfully!"
        except mysql.connector.Error as e:
            message = f"MySQL Error: {e}"

    # Fetch User Details
    cursor.execute("SELECT id, username, email, first_name, last_name, contact, created_at FROM shop_users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()

    # Fetch User Addresses
    cursor.execute("SELECT * FROM address WHERE user_id = %s", (user_id,))
    addresses = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('profile.html', user=user_data, addresses=addresses, message=message, query=query_executed)

if __name__ == '__main__':
    # Use PORT injected by Clever Cloud, default to 5000 for local dev
    port = int(os.getenv("PORT", 5000))
    # Turn off debug mode for production deployment
    app.run(host="0.0.0.0", port=port, debug=False)