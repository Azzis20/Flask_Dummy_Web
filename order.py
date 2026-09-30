
from flask import Blueprint, request, render_template, redirect, url_for, session
import mysql.connector
from utils import get_db_connection, login_required

order_bp = Blueprint('order', __name__, url_prefix='/orders')


# 1. ADD TO CART
@order_bp.route('/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session['cart'] = cart

    return redirect(url_for('order.view_cart'))


# 2. VIEW CART
@order_bp.route('/cart', methods=['GET'])
@login_required
def view_cart():
    cart = session.get('cart', {})
    cart_items = []
    total_price = 0.0
    user_id = session.get('user_id')
    addresses = []

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if cart:
            placeholders = ', '.join(['%s'] * len(cart))
            query = f"SELECT id, product_name, price FROM Products WHERE id IN ({placeholders})"
            cursor.execute(query, list(cart.keys()))
            products = cursor.fetchall()

            for p in products:
                qty = cart[str(p['id'])]
                price = float(p['price']) if p['price'] is not None else 0.0
                subtotal = price * qty
                total_price += subtotal
                cart_items.append({
                    'product_id': p['id'],
                    'product_name': p['product_name'],
                    'price': price,
                    'quantity': qty,
                    'subtotal': subtotal
                })

        cursor.execute("SELECT * FROM Address WHERE user_id = %s", (user_id,))
        addresses = cursor.fetchall()

    except mysql.connector.Error as e:
        return f"Database Error: {e}", 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    return render_template('cart.html', cart_items=cart_items, total_price=total_price, addresses=addresses)


# 3. CHECKOUT
@order_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    user_id = session.get('user_id')
    cart = session.get('cart', {})
    address_text = request.form.get('address')
    contact_number = request.form.get('contact_number')

    if not cart:
        return redirect(url_for('product.products'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        placeholders = ', '.join(['%s'] * len(cart))
        cursor.execute(
            f"SELECT id, product_name, price, stock_quantity FROM Products WHERE id IN ({placeholders})",
            list(cart.keys())
        )
        products = cursor.fetchall()

        # Guard against stale/invalid cart entries (product deleted, etc.)
        if not products:
            return "Order Failed: no valid products in cart", 400

        # Validate stock before committing to anything
        for p in products:
            qty = cart[str(p['id'])]
            if p['stock_quantity'] is not None and qty > p['stock_quantity']:
                return f"Order Failed: not enough stock for {p['product_name']}", 400

        item_summary = ", ".join([f"{p['product_name']} (x{cart[str(p['id'])]})" for p in products])
        order_query = """
            INSERT INTO orders (user_id, item, status, address, contact_number)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(order_query, (user_id, item_summary, 'Pending', address_text, contact_number))
        order_id = cursor.lastrowid

        for p in products:
            qty = cart[str(p['id'])]
            item_query = """
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(item_query, (order_id, p['id'], qty, p['price']))
            cursor.execute("UPDATE Products SET stock_quantity = stock_quantity - %s WHERE id = %s", (qty, p['id']))

        conn.commit()
        session.pop('cart', None)
        return redirect(url_for('order.order_history'))

    except mysql.connector.Error as e:
        if conn is not None:
            conn.rollback()
        return f"Order Failed: {e}", 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 4. ORDER HISTORY
@order_bp.route('/history', methods=['GET'])
@login_required
def order_history():
    user_id = session.get('user_id')

    print("DEBUG user_id:", user_id)

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        print("DEBUG: database connected")

        cursor.execute(
            """
            SELECT id, user_id, item, status, address, contact_number
            FROM orders
            WHERE user_id = %s
            ORDER BY id DESC
            """,
            (user_id,)
        )

        orders = cursor.fetchall()

        print("DEBUG orders:", orders)

        for order in orders:

            cursor.execute(
                """
                SELECT
                    oi.id,
                    oi.order_id,
                    oi.product_id,
                    oi.quantity,
                    oi.unit_price,
                    p.product_name
                FROM order_items oi
                JOIN products p
                    ON oi.product_id = p.id
                WHERE oi.order_id = %s
                """,
                (order['id'],)
            )

            raw_items = cursor.fetchall()

            print("DEBUG order", order['id'], "items:", raw_items)

            for item in raw_items:
                if item['unit_price'] is not None:
                    item['unit_price'] = float(item['unit_price'])

            order['items'] = raw_items

        print("DEBUG: rendering template")

        return render_template(
            'order_history.html',
            orders=orders
        )

    except Exception as e:
        print("====================================")
        print("ORDER HISTORY ERROR:")
        print(repr(e))
        import traceback
        traceback.print_exc()
        print("====================================")

        return f"Order history error: {e}", 500

    finally:
        if cursor is not None:
            cursor.close()

        if conn is not None:
            conn.close()



# 5. ORDER LOOKUP / TRACKING
@order_bp.route('/track', methods=['GET', 'POST'])
@login_required
def track_order():
    order_id_raw = request.values.get('order_id', '')
    order_data = None
    error_msg = None
    user_id = session.get('user_id')

    if order_id_raw:
        if not order_id_raw.isdigit():
            error_msg = "Invalid order ID."
        else:
            order_id = int(order_id_raw)
            conn = None
            cursor = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                # Join with users to get the customer's name.
                # Adjust "u.name" below to whatever column your users table
                # actually uses (e.g. u.username, u.full_name).
                cursor.execute(
                    "SELECT o.id AS order_id, "
                    "CONCAT(u.first_name, ' ', u.last_name) AS customer_name, "
                    "o.item, o.status "
                    "FROM orders o "
                    "JOIN shop_users u ON u.id = o.user_id "
                    "WHERE o.id = %s AND o.user_id = %s",
                    (order_id, user_id)
                )
                order_data = cursor.fetchall()
                if not order_data:
                    error_msg = "Order not found."
            except mysql.connector.Error as e:
                error_msg = "A database error occurred while looking up your order."
            finally:
                if cursor is not None:
                    cursor.close()
                if conn is not None:
                    conn.close()

    return render_template('order_track.html', order=order_data, order_id=order_id_raw, error=error_msg)


# 6. CANCEL ORDER
@order_bp.route('/cancel/<int:order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    user_id = session.get('user_id')

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = 'Cancelled' WHERE id = %s AND user_id = %s AND status = 'Pending'",
            (order_id, user_id)
        )
        conn.commit()
    except mysql.connector.Error as e:
        if conn is not None:
            conn.rollback()
        return f"Cancel Failed: {e}", 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    return redirect(url_for('order.order_history'))