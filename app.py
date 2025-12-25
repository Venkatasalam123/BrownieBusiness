from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from config import USE_GOOGLE_SHEETS

# Import appropriate models based on configuration
if USE_GOOGLE_SHEETS:
    from gs_models import db, Variety, Shop, Order, session as gs_session
    print("📊 Using Google Sheets as database")
    # Create a mock session object for compatibility
    class MockSession:
        def __getattr__(self, name):
            return getattr(gs_session, name)
    db_session = MockSession()
else:
    from models import db, Variety, Shop, Order
    from sqlalchemy import func, extract, text
    print("💾 Using SQLite as database")
    db_session = db.session

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'

if not USE_GOOGLE_SHEETS:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownie_sales.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    # Initialize database
    with app.app_context():
        db.create_all()
else:
    db.init_app(app)
    # Initialize Google Sheets
    with app.app_context():
        db.create_all()


@app.route('/')
def index():
    """Dashboard with quick order entry form"""
    varieties = Variety.query.order_by(Variety.name).all()
    shops = Shop.query.order_by(Shop.name).all()
    return render_template('index.html', varieties=varieties, shops=shops)


@app.route('/orders/add', methods=['POST'])
def add_order():
    """Add new order"""
    try:
        variety_id = request.form.get('variety_id', type=int)
        shop_id = request.form.get('shop_id', type=int)
        quantity = request.form.get('quantity', type=int)
        price = request.form.get('price', type=float)
        delivery_date_str = request.form.get('delivery_date')
        payment_status = request.form.get('payment_status', 'unpaid')
        paid_amount = request.form.get('paid_amount', type=float) or 0
        
        # Validation
        if not variety_id or not shop_id or not quantity or not price or not delivery_date_str:
            flash('All fields are required', 'error')
            return redirect(url_for('index'))
        
        if quantity <= 0 or price <= 0:
            flash('Quantity and price must be positive numbers', 'error')
            return redirect(url_for('index'))
        
        # Validate payment status
        if payment_status not in ['paid', 'unpaid', 'partial']:
            payment_status = 'unpaid'
        
        # Validate paid amount
        total_amount = float(price * quantity)
        if payment_status == 'paid':
            paid_amount = total_amount
        elif payment_status == 'partial':
            if paid_amount <= 0 or paid_amount >= total_amount:
                flash('Partial payment amount must be greater than 0 and less than total amount', 'error')
                return redirect(url_for('index'))
        else:  # unpaid
            paid_amount = 0
        
        # Parse delivery date
        try:
            delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('index'))
        
        # Verify variety and shop exist
        variety = Variety.query.get_or_404(variety_id)
        shop = Shop.query.get_or_404(shop_id)
        
        # Create order
        order = Order(
            variety_id=variety_id,
            shop_id=shop_id,
            quantity=quantity,
            price=Decimal(str(price)),
            delivery_date=delivery_date,
            payment_status=payment_status,
            paid_amount=Decimal(str(paid_amount))
        )
        
        db_session.add(order)
        db_session.commit()
        
        flash(f'Order added successfully! Total: ₹{float(order.price * order.quantity):.2f}', 'success')
        return redirect(url_for('index'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error adding order: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/varieties')
def varieties():
    """List and manage varieties"""
    varieties_list = Variety.query.order_by(Variety.name).all()
    return render_template('varieties.html', varieties=varieties_list)


@app.route('/varieties/add', methods=['POST'])
def add_variety():
    """Add new variety"""
    try:
        name = request.form.get('name', '').strip()
        default_price = request.form.get('default_price', type=float)
        
        if not name or default_price is None:
            flash('Name and default price are required', 'error')
            return redirect(url_for('varieties'))
        
        if default_price <= 0:
            flash('Default price must be a positive number', 'error')
            return redirect(url_for('varieties'))
        
        # Check for duplicate
        existing = Variety.query.filter_by(name=name).first()
        if existing:
            flash('A variety with this name already exists', 'error')
            return redirect(url_for('varieties'))
        
        variety = Variety(name=name, default_price=Decimal(str(default_price)))
        db_session.add(variety)
        db_session.commit()
        
        flash(f'Variety "{name}" added successfully', 'success')
        return redirect(url_for('varieties'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error adding variety: {str(e)}', 'error')
        return redirect(url_for('varieties'))


@app.route('/varieties/update/<int:id>', methods=['POST'])
def update_variety(id):
    """Update variety"""
    try:
        variety = Variety.query.get_or_404(id)
        name = request.form.get('name', '').strip()
        default_price = request.form.get('default_price', type=float)
        
        if not name or default_price is None:
            flash('Name and default price are required', 'error')
            return redirect(url_for('varieties'))
        
        if default_price <= 0:
            flash('Default price must be a positive number', 'error')
            return redirect(url_for('varieties'))
        
        # Check for duplicate (excluding current variety)
        existing = Variety.query.filter_by(name=name).first()
        if existing and existing.id != id:
            flash('A variety with this name already exists', 'error')
            return redirect(url_for('varieties'))
        
        if USE_GOOGLE_SHEETS:
            # For Google Sheets, update via API
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_variety(id, name, Decimal(str(default_price)))
        else:
            # For SQLite, update the object and commit
            variety.name = name
            variety.default_price = Decimal(str(default_price))
            db_session.commit()
        
        flash(f'Variety "{name}" updated successfully', 'success')
        return redirect(url_for('varieties'))
    
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error updating variety: {str(e)}', 'error')
        return redirect(url_for('varieties'))


@app.route('/varieties/delete/<int:id>', methods=['POST'])
def delete_variety(id):
    """Delete variety"""
    try:
        variety = Variety.query.get_or_404(id)
        name = variety.name
        db_session.delete(variety)
        db_session.commit()
        
        flash(f'Variety "{name}" deleted successfully', 'success')
        return redirect(url_for('varieties'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error deleting variety: {str(e)}', 'error')
        return redirect(url_for('varieties'))


@app.route('/shops')
def shops():
    """List and manage shops"""
    shops_list = Shop.query.order_by(Shop.name).all()
    
    # Calculate pending amounts for each shop
    shops_with_pending = []
    for shop in shops_list:
        orders = Order.query.filter_by(shop_id=shop.id).all()
        total_pending = 0
        unpaid_count = 0
        
        for order in orders:
            order_total = float(order.price * order.quantity)
            paid_amt = float(order.paid_amount) if order.paid_amount else 0
            pending_amt = order_total - paid_amt
            if pending_amt > 0:
                total_pending += pending_amt
                unpaid_count += 1
        
        shops_with_pending.append({
            'shop': shop,
            'pending': total_pending,
            'unpaid_count': unpaid_count
        })
    
    return render_template('shops.html', shops_with_pending=shops_with_pending)


@app.route('/shops/add', methods=['POST'])
def add_shop():
    """Add new shop/customer"""
    try:
        name = request.form.get('name', '').strip()
        
        if not name:
            flash('Name is required', 'error')
            return redirect(url_for('shops'))
        
        # Check for duplicate
        existing = Shop.query.filter_by(name=name).first()
        if existing:
            flash('A shop/customer with this name already exists', 'error')
            return redirect(url_for('shops'))
        
        shop = Shop(name=name)
        db_session.add(shop)
        db_session.commit()
        
        flash(f'Shop/Customer "{name}" added successfully', 'success')
        return redirect(url_for('shops'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error adding shop: {str(e)}', 'error')
        return redirect(url_for('shops'))


@app.route('/shops/update/<int:id>', methods=['POST'])
def update_shop(id):
    """Update shop/customer"""
    try:
        shop = Shop.query.get_or_404(id)
        name = request.form.get('name', '').strip()
        
        if not name:
            flash('Name is required', 'error')
            return redirect(url_for('shops'))
        
        # Check for duplicate (excluding current shop)
        existing = Shop.query.filter_by(name=name).first()
        if existing and existing.id != id:
            flash('A shop/customer with this name already exists', 'error')
            return redirect(url_for('shops'))
        
        if USE_GOOGLE_SHEETS:
            # For Google Sheets, update via API
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_shop(id, name)
        else:
            # For SQLite, update the object and commit
            shop.name = name
            db_session.commit()
        
        flash(f'Shop/Customer "{name}" updated successfully', 'success')
        return redirect(url_for('shops'))
    
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error updating shop: {str(e)}', 'error')
        return redirect(url_for('shops'))


@app.route('/shops/delete/<int:id>', methods=['POST'])
def delete_shop(id):
    """Delete shop/customer"""
    try:
        shop = Shop.query.get_or_404(id)
        name = shop.name
        db_session.delete(shop)
        db_session.commit()
        
        flash(f'Shop/Customer "{name}" deleted successfully', 'success')
        return redirect(url_for('shops'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error deleting shop: {str(e)}', 'error')
        return redirect(url_for('shops'))


@app.route('/orders')
def orders():
    """Order history page - shows all orders grouped by month, then by date"""
    # Get all orders ordered by delivery date (newest first)
    all_orders = Order.query.order_by(Order.delivery_date.desc(), Order.created_at.desc()).all()
    
    # Group orders by month, then by date
    orders_by_month = {}
    total_sales = 0
    total_pending = 0
    
    for order in all_orders:
        # Create month key (YYYY-MM format)
        month_key = order.delivery_date.strftime('%Y-%m')
        month_label = order.delivery_date.strftime('%B %Y')
        date_str = order.delivery_date.isoformat()
        
        if month_key not in orders_by_month:
            orders_by_month[month_key] = {
                'label': month_label,
                'dates': {},
                'month_total': 0,
                'month_pending': 0
            }
        
        if date_str not in orders_by_month[month_key]['dates']:
            orders_by_month[month_key]['dates'][date_str] = {'orders': [], 'date_total': 0, 'date_pending': 0}
        
        orders_by_month[month_key]['dates'][date_str]['orders'].append(order)
        order_total = float(order.price * order.quantity)
        paid_amt = float(order.paid_amount) if order.paid_amount else 0
        pending_amt = order_total - paid_amt
        
        orders_by_month[month_key]['dates'][date_str]['date_total'] += order_total
        orders_by_month[month_key]['dates'][date_str]['date_pending'] += pending_amt
        orders_by_month[month_key]['month_total'] += order_total
        orders_by_month[month_key]['month_pending'] += pending_amt
        total_sales += order_total
        total_pending += pending_amt
    
    # Convert to list sorted by month (newest first)
    months_grouped = []
    for month_key in sorted(orders_by_month.keys(), reverse=True):
        month_data = orders_by_month[month_key]
        # Sort dates within month (newest first)
        dates_list = []
        month_order_count = 0
        for date_str in sorted(month_data['dates'].keys(), reverse=True):
            date_data = month_data['dates'][date_str]
            dates_list.append((date_str, date_data['orders'], date_data['date_total'], date_data['date_pending']))
            month_order_count += len(date_data['orders'])
        months_grouped.append((month_key, month_data['label'], dates_list, month_data['month_total'], month_data['month_pending'], month_order_count))
    
    # Convert UTC times to IST for display (IST is UTC+5:30)
    ist_offset = timedelta(hours=5, minutes=30)
    return render_template('orders.html', months_grouped=months_grouped, total_sales=total_sales, total_pending=total_pending, total_orders=len(all_orders), ist_offset=ist_offset)


@app.route('/reports')
def reports():
    """Monthly sales report page"""
    # Get current month and year as default
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Get all available years and months for dropdown
    if USE_GOOGLE_SHEETS:
        # For Google Sheets, get years from all orders
        all_orders = Order.query.all()
        years = sorted(set(order.delivery_date.year for order in all_orders if order.delivery_date), reverse=True)
    else:
        years = db.session.query(extract('year', Order.delivery_date).label('year')).distinct().order_by(text('year desc')).all()
        years = [int(y[0]) for y in years if y[0]]
    
    return render_template('reports.html', 
                         current_month=current_month, 
                         current_year=current_year,
                         available_years=years if years else [current_year])


@app.route('/api/reports/overall')
def api_overall_report():
    """JSON API endpoint for overall/all-time report data"""
    try:
        # Get all orders
        orders = Order.query.all()
        
        # Calculate totals
        total_sales = sum(float(order.price * order.quantity) for order in orders)
        total_paid = sum(float(order.paid_amount) if order.paid_amount else 0 for order in orders)
        total_pending = total_sales - total_paid
        margin = total_sales * 0.30
        
        # Shop-wise breakdown with pending amounts (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets
            shop_dict = {}
            for order in orders:
                shop = order.shop
                shop_name = shop.name if shop else 'Unknown'
                if shop_name not in shop_dict:
                    shop_dict[shop_name] = {'total': 0, 'paid': 0}
                shop_dict[shop_name]['total'] += float(order.price * order.quantity)
                shop_dict[shop_name]['paid'] += float(order.paid_amount) if order.paid_amount else 0
            
            shop_totals = sorted(
                [(name, data['total'], data['paid']) for name, data in shop_dict.items()],
                key=lambda x: x[1], reverse=True
            )
        else:
            shop_totals = db.session.query(
                Shop.name,
                func.sum(Order.price * Order.quantity).label('total'),
                func.sum(func.coalesce(Order.paid_amount, 0)).label('paid')
            ).join(Order).group_by(Shop.id, Shop.name).order_by(text('total desc')).all()
        
        shop_data = {
            'labels': [s[0] for s in shop_totals],
            'values': [float(s[1]) for s in shop_totals],
            'pending': [float(s[1]) - float(s[2]) for s in shop_totals]
        }
        
        # Variety-wise breakdown (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets
            variety_dict = {}
            for order in orders:
                variety = order.variety
                variety_name = variety.name if variety else 'Unknown'
                if variety_name not in variety_dict:
                    variety_dict[variety_name] = 0
                variety_dict[variety_name] += float(order.price * order.quantity)
            
            variety_totals = sorted(
                [(name, total) for name, total in variety_dict.items()],
                key=lambda x: x[1], reverse=True
            )
        else:
            variety_totals = db.session.query(
                Variety.name,
                func.sum(Order.price * Order.quantity).label('total')
            ).join(Order).group_by(Variety.id, Variety.name).order_by(text('total desc')).all()
        
        variety_data = {
            'labels': [v[0] for v in variety_totals],
            'values': [float(v[1]) for v in variety_totals]
        }
        
        # Summary statistics
        total_orders = len(orders)
        avg_order_value = total_sales / total_orders if total_orders > 0 else 0
        
        return jsonify({
            'total_sales': round(total_sales, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_pending, 2),
            'margin': round(margin, 2),
            'shop_data': shop_data,
            'variety_data': variety_data,
            'total_orders': total_orders,
            'avg_order_value': round(avg_order_value, 2)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/monthly/<int:year>/<int:month>')
def api_monthly_report(year, month):
    """JSON API endpoint for monthly report data"""
    try:
        # Get all orders for the month
        if USE_GOOGLE_SHEETS:
            all_orders = Order.query.all()
            orders = [
                order for order in all_orders
                if order.delivery_date and order.delivery_date.year == year and order.delivery_date.month == month
            ]
        else:
            orders = Order.query.filter(
                extract('year', Order.delivery_date) == year,
                extract('month', Order.delivery_date) == month
            ).all()
        
        # Calculate totals
        total_sales = sum(float(order.price * order.quantity) for order in orders)
        total_paid = sum(float(order.paid_amount) if order.paid_amount else 0 for order in orders)
        total_pending = total_sales - total_paid
        margin = total_sales * 0.30
        
        # Shop-wise breakdown with pending amounts (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets (already filtered by month/year above)
            shop_dict = {}
            for order in orders:
                shop = order.shop
                shop_name = shop.name if shop else 'Unknown'
                if shop_name not in shop_dict:
                    shop_dict[shop_name] = {'total': 0, 'paid': 0}
                shop_dict[shop_name]['total'] += float(order.price * order.quantity)
                shop_dict[shop_name]['paid'] += float(order.paid_amount) if order.paid_amount else 0
            
            shop_totals = sorted(
                [(name, data['total'], data['paid']) for name, data in shop_dict.items()],
                key=lambda x: x[1], reverse=True
            )
        else:
            shop_totals = db.session.query(
                Shop.name,
                func.sum(Order.price * Order.quantity).label('total'),
                func.sum(func.coalesce(Order.paid_amount, 0)).label('paid')
            ).join(Order).filter(
                extract('year', Order.delivery_date) == year,
                extract('month', Order.delivery_date) == month
            ).group_by(Shop.id, Shop.name).order_by(text('total desc')).all()
        
        shop_data = {
            'labels': [s[0] for s in shop_totals],
            'values': [float(s[1]) for s in shop_totals],
            'pending': [float(s[1]) - float(s[2]) for s in shop_totals]
        }
        
        # Variety-wise breakdown (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets (already filtered by month/year above)
            variety_dict = {}
            for order in orders:
                variety = order.variety
                variety_name = variety.name if variety else 'Unknown'
                if variety_name not in variety_dict:
                    variety_dict[variety_name] = 0
                variety_dict[variety_name] += float(order.price * order.quantity)
            
            variety_totals = sorted(
                [(name, total) for name, total in variety_dict.items()],
                key=lambda x: x[1], reverse=True
            )
        else:
            variety_totals = db.session.query(
                Variety.name,
                func.sum(Order.price * Order.quantity).label('total')
            ).join(Order).filter(
                extract('year', Order.delivery_date) == year,
                extract('month', Order.delivery_date) == month
            ).group_by(Variety.id, Variety.name).order_by(text('total desc')).all()
        
        variety_data = {
            'labels': [v[0] for v in variety_totals],
            'values': [float(v[1]) for v in variety_totals]
        }
        
        # Summary statistics
        total_orders = len(orders)
        avg_order_value = total_sales / total_orders if total_orders > 0 else 0
        
        return jsonify({
            'total_sales': round(total_sales, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_pending, 2),
            'margin': round(margin, 2),
            'shop_data': shop_data,
            'variety_data': variety_data,
            'total_orders': total_orders,
            'avg_order_value': round(avg_order_value, 2)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/shops/<int:id>/bill')
def shop_bill(id):
    """Generate bill for a shop showing unpaid orders"""
    shop = Shop.query.get_or_404(id)
    
    # Get all unpaid or partially paid orders for this shop
    all_orders = Order.query.filter_by(shop_id=id).order_by(Order.delivery_date.desc()).all()
    
    unpaid_orders = []
    total_pending = 0
    
    for order in all_orders:
        order_total = float(order.price * order.quantity)
        paid_amt = float(order.paid_amount) if order.paid_amount else 0
        pending_amt = order_total - paid_amt
        
        if pending_amt > 0:
            unpaid_orders.append({
                'order': order,
                'total': order_total,
                'paid': paid_amt,
                'pending': pending_amt
            })
            total_pending += pending_amt
    
    bill_date = datetime.now()
    return render_template('bill.html', shop=shop, unpaid_orders=unpaid_orders, total_pending=total_pending, bill_date=bill_date)


@app.route('/orders/edit/<int:id>', methods=['GET', 'POST'])
def edit_order(id):
    """Edit an existing order"""
    order = Order.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            variety_id = request.form.get('variety_id', type=int)
            shop_id = request.form.get('shop_id', type=int)
            quantity = request.form.get('quantity', type=int)
            price = request.form.get('price', type=float)
            delivery_date_str = request.form.get('delivery_date')
            payment_status = request.form.get('payment_status', default='unpaid')
            paid_amount = request.form.get('paid_amount', type=float, default=0.00)
            
            # Validation
            if not variety_id or not shop_id or not quantity or not price or not delivery_date_str:
                flash('All fields are required', 'error')
                return redirect(url_for('edit_order', id=id))
            
            if quantity <= 0 or price <= 0:
                flash('Quantity and price must be positive numbers', 'error')
                return redirect(url_for('edit_order', id=id))
            
            # Parse delivery date
            try:
                delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format', 'error')
                return redirect(url_for('edit_order', id=id))
            
            # Verify variety and shop exist
            variety = Variety.query.get_or_404(variety_id)
            shop = Shop.query.get_or_404(shop_id)
            
            # Update order
            if USE_GOOGLE_SHEETS:
                # For Google Sheets, update via API
                from google_sheets import get_gs_db
                gs = get_gs_db()
                gs.update_order(
                    id,
                    variety_id,
                    shop_id,
                    quantity,
                    Decimal(str(price)),
                    delivery_date,
                    payment_status,
                    Decimal(str(paid_amount))
                )
                total = float(Decimal(str(price)) * quantity)
            else:
                # For SQLite, update the object and commit
                order.variety_id = variety_id
                order.shop_id = shop_id
                order.quantity = quantity
                order.price = Decimal(str(price))
                order.delivery_date = delivery_date
                order.payment_status = payment_status
                order.paid_amount = Decimal(str(paid_amount))
                db_session.commit()
                total = float(order.price * order.quantity)
            
            flash(f'Order updated successfully! Total: ₹{total:.2f}', 'success')
            return redirect(url_for('orders'))
        
        except Exception as e:
            if not USE_GOOGLE_SHEETS:
                db_session.rollback()
            flash(f'Error updating order: {str(e)}', 'error')
            return redirect(url_for('edit_order', id=id))
    
    # GET request - show edit form
    varieties = Variety.query.order_by(Variety.name).all()
    shops = Shop.query.order_by(Shop.name).all()
    return render_template('edit_order.html', order=order, varieties=varieties, shops=shops)


@app.route('/orders/delete-all', methods=['POST'])
def delete_all_orders():
    """Delete all orders from database"""
    try:
        count = Order.query.count()
        Order.query.delete()
        db_session.commit()
        flash(f'Successfully deleted {count} order(s)', 'success')
        return redirect(url_for('orders'))
    except Exception as e:
        db_session.rollback()
        flash(f'Error deleting orders: {str(e)}', 'error')
        return redirect(url_for('orders'))


if __name__ == '__main__':
    app.run(debug=True)

