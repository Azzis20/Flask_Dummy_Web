from flask import Blueprint, request, render_template
import mysql.connector
from utils import get_db_connection, login_required

product_bp = Blueprint('product', __name__, url_prefix='/products')

@product_bp.route('/')
@login_required
def products():
    search = request.args.get('q', '')
    query_executed = None
    products_list = []
    error_msg = None

    if search:
        raw_query = f"SELECT id, product_name, category, price, stock_quantity FROM products WHERE category = '{search}' OR product_name LIKE '%{search}%'"
    else:
        raw_query = "SELECT id, product_name, category, price, stock_quantity FROM products WHERE is_active = 1"

    query_executed = raw_query

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(raw_query)
        products_list = cursor.fetchall()
        conn.close()
    except mysql.connector.Error as e:
        error_msg = f"MySQL Error: {e}"

    return render_template('products.html', products=products_list, search=search, query=query_executed, error=error_msg)