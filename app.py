from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from config import USE_GOOGLE_SHEETS

# Import appropriate models based on configuration
if USE_GOOGLE_SHEETS:
    from gs_models import db, Variety, Shop, Order, IngredientPrice, session as gs_session
    print("📊 Using Google Sheets as database")
    # Create a mock session object for compatibility
    class MockSession:
        def __getattr__(self, name):
            return getattr(gs_session, name)
    db_session = MockSession()
else:
    from models import db, Variety, Shop, Order, IngredientPrice
    from sqlalchemy import func, extract, text
    print("💾 Using SQLite as database")
    db_session = db.session

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'

# Make USE_GOOGLE_SHEETS available to all templates
@app.context_processor
def inject_config():
    return dict(USE_GOOGLE_SHEETS=USE_GOOGLE_SHEETS)

def _update_miscellaneous_cost():
    """Update Miscellaneous cost from ₹10 to ₹15 if needed (for both SQLite and Google Sheets)"""
    if IngredientPrice is None:
        return
    
    miscellaneous = IngredientPrice.query.filter_by(name='Miscellaneous').first()
    if miscellaneous and float(miscellaneous.price) == 10:
        # Update to ₹15
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_ingredient_price(
                miscellaneous.id,
                'Miscellaneous',
                Decimal('15'),
                '16 brownies',
                Decimal('16'),
                'pc'
            )
        else:
            miscellaneous.price = Decimal('15')
            miscellaneous.updated_at = datetime.utcnow()
            db_session.commit()


if not USE_GOOGLE_SHEETS:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownie_sales.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    # Initialize database
    with app.app_context():
        db.create_all()
        # Initialize default ingredient prices if they don't exist
        _initialize_default_ingredient_prices()
        # Update Miscellaneous cost if needed
        _update_miscellaneous_cost()
else:
    db.init_app(app)
    # Initialize Google Sheets (this will also initialize ingredient prices)
    with app.app_context():
        db.create_all()
        # Update Miscellaneous cost if needed
        _update_miscellaneous_cost()


def _initialize_default_ingredient_prices():
    """Initialize default ingredient prices if they don't exist"""
    if IngredientPrice is None:
        return
    
    default_prices = [
        {'name': 'Dark Compound', 'price': 165, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Butter', 'price': 100, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Egg', 'price': 7, 'unit': '1pc', 'package_size': 1, 'package_unit': 'pc'},
        {'name': 'White Sugar', 'price': 50, 'unit': '1kg', 'package_size': 1, 'package_unit': 'kg'},
        {'name': 'Brown Sugar', 'price': 80, 'unit': '1kg', 'package_size': 1, 'package_unit': 'kg'},
        {'name': 'Vanilla Essence', 'price': 50, 'unit': '100ml', 'package_size': 100, 'package_unit': 'ml'},
        {'name': 'Maida/Ragi', 'price': 50, 'unit': '1kg', 'package_size': 1, 'package_unit': 'kg'},
        {'name': 'Mango Compound', 'price': 205, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Pista Compound', 'price': 205, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Strawberry Compound', 'price': 200, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Pineapple Compound', 'price': 200, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Pista Nuts', 'price': 445, 'unit': '250g', 'package_size': 250, 'package_unit': 'g'},
        {'name': 'Milk Compound', 'price': 190, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'White Compound', 'price': 205, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'Oven Charges', 'price': 20, 'unit': '16 brownies', 'package_size': 16, 'package_unit': 'pc'},
        {'name': 'Miscellaneous', 'price': 15, 'unit': '16 brownies', 'package_size': 16, 'package_unit': 'pc'},
        {'name': 'Packing', 'price': 28.8, 'unit': '16 brownies', 'package_size': 16, 'package_unit': 'pc'},
        {'name': 'Transportation', 'price': 20, 'unit': '16 brownies', 'package_size': 16, 'package_unit': 'pc'},
    ]
    
    for ing_data in default_prices:
        existing = IngredientPrice.query.filter_by(name=ing_data['name']).first()
        if not existing:
            ingredient = IngredientPrice(
                name=ing_data['name'],
                price=Decimal(str(ing_data['price'])),
                unit=ing_data['unit'],
                package_size=Decimal(str(ing_data['package_size'])),
                package_unit=ing_data['package_unit']
            )
            db_session.add(ingredient)
        elif ing_data['name'] == 'Pista Nuts' and existing.package_size == 25:
            # Update existing Pista Nuts if it still has old value (25g)
            existing.price = Decimal(str(ing_data['price']))
            existing.unit = ing_data['unit']
            existing.package_size = Decimal(str(ing_data['package_size']))
            existing.package_unit = ing_data['package_unit']
            existing.updated_at = datetime.utcnow()
        elif ing_data['name'] == 'Miscellaneous' and float(existing.price) == 10:
            # Update existing Miscellaneous if it still has old value (₹10)
            existing.price = Decimal(str(ing_data['price']))
            existing.unit = ing_data['unit']
            existing.package_size = Decimal(str(ing_data['package_size']))
            existing.package_unit = ing_data['package_unit']
            existing.updated_at = datetime.utcnow()
    
    db_session.commit()


def get_ingredient_price(name):
    """Get ingredient price object by name"""
    if IngredientPrice is None:
        return None
    return IngredientPrice.query.filter_by(name=name).first()


# For sales calculations, always use actual order.price from database
# The calculated price from get_cost_breakdown() should only be used for cost calculations, not sales


def get_brownies_in_combo_pack(variety):
    """Get the total number of brownies in a combo pack variety"""
    if not variety or not variety.is_combo_pack():
        return 0
    
    combo_items = variety.get_combo_pack_varieties()
    total_brownies = 0
    
    for item in combo_items:
        if isinstance(item, dict):
            quantity = item.get('quantity', 1)
        else:
            # Backward compatibility: old format was just IDs
            quantity = 1
        total_brownies += quantity
    
    return total_brownies


def calculate_cost_per_brownie(variety_name):
    """Calculate the cost per brownie based on variety and ingredient prices
    Uses get_cost_breakdown() to ensure consistency with ingredients page display
    """
    if IngredientPrice is None:
        return None
    
    # Use get_cost_breakdown to get the exact same calculation as ingredients page
    breakdown = get_cost_breakdown(variety_name)
    if breakdown:
        return breakdown.get('cost_per_brownie', None)
    return None


def get_cost_breakdown(variety_name):
    """Get detailed cost breakdown for a variety showing how cost per brownie is calculated"""
    if IngredientPrice is None:
        return None
    
    # Check if this is a combo pack
    variety = Variety.query.filter_by(name=variety_name).first()
    if variety and variety.is_combo_pack():
        # Get the variety IDs in this combo pack
        combo_variety_ids = variety.get_combo_pack_varieties()
        
        breakdown = {
            'variety': variety_name,
            'ingredients': [],
            'total_cost_16_brownies': 0,
            'cost_per_brownie': 0
        }
        
        # Get extra packing cost from variety config (defaults to 5.0)
        extra_packing_cost = variety.get_extra_packing_cost()
        combo_cost = 0.0
        total_brownies_in_combo = 0  # Count total brownies in combo pack
        
        # Add cost for each brownie in the combo pack (with quantities)
        for item in combo_variety_ids:
            # Handle both old format (int) and new format (dict)
            if isinstance(item, dict):
                variety_id = item.get('id')
                quantity = item.get('quantity', 1)
            else:
                # Backward compatibility: old format was just IDs
                variety_id = item
                quantity = 1
            
            total_brownies_in_combo += quantity  # Count brownies
            
            combo_variety = Variety.query.get(variety_id)
            if combo_variety:
                # Skip if it's also a combo pack (avoid recursion)
                if not combo_variety.is_combo_pack():
                    brownie_breakdown = get_cost_breakdown(combo_variety.name)
                    if brownie_breakdown:
                        brownie_cost = brownie_breakdown.get('cost_per_brownie', 0)
                        # Subtract ₹1 miscellaneous cost (we'll add it separately for all brownies in combo)
                        brownie_cost_without_misc = brownie_cost - 1.0
                        total_item_cost = brownie_cost_without_misc * quantity
                        combo_cost += total_item_cost
                        breakdown['ingredients'].append({
                            'name': combo_variety.name,
                            'quantity': f'{quantity} brownie{"s" if quantity > 1 else ""}',
                            'package_price': 0,
                            'package_size': '1 brownie',
                            'price_per_unit': brownie_cost_without_misc,
                            'cost': total_item_cost
                        })
        
        # Add variety miscellaneous cost (₹1 per brownie in combo pack)
        # This is calculated based on total number of brownies in the combo pack
        variety_misc_cost = total_brownies_in_combo * 1.0  # ₹1 per brownie
        combo_cost += variety_misc_cost
        breakdown['ingredients'].append({
            'name': 'Variety Miscellaneous Cost',
            'quantity': f'{total_brownies_in_combo} brownie{"s" if total_brownies_in_combo > 1 else ""} (₹1 per brownie)',
            'package_price': 0,
            'package_size': '1 brownie',
            'price_per_unit': 1.0,
            'cost': variety_misc_cost
        })
        
        # Add extra packing cost
        combo_cost += extra_packing_cost
        breakdown['ingredients'].append({
            'name': 'Extra Packing',
            'quantity': '1 combo pack',
            'package_price': extra_packing_cost,
            'package_size': '1 combo pack',
            'price_per_unit': extra_packing_cost,
            'cost': extra_packing_cost
        })
        
        breakdown['cost_per_brownie'] = combo_cost
        breakdown['total_cost_16_brownies'] = combo_cost  # For 1 combo pack
        
        return breakdown
    
    breakdown = {
        'variety': variety_name,
        'ingredients': [],
        'total_cost_16_brownies': 0,
        'cost_per_brownie': 0
    }
    
    # Ingredients needed for 16 brownies
    butter_g = 235
    egg_count = 4
    white_sugar_g = 52
    brown_sugar_g = 52
    vanilla_essence_ml = 4
    maida_ragi_g = 125
    compound_g = 400
    
    # Base ingredients
    butter = get_ingredient_price('Butter')
    if butter:
        price_per_g = butter.get_price_per_gram()
        if price_per_g:
            cost = butter_g * price_per_g
            breakdown['ingredients'].append({
                'name': 'Butter',
                'quantity': f'{butter_g}g',
                'package_price': float(butter.price),
                'package_size': f'{butter.unit}',
                'price_per_unit': price_per_g,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    egg = get_ingredient_price('Egg')
    if egg:
        price_per_piece = egg.get_price_per_piece()
        if price_per_piece:
            cost = egg_count * price_per_piece
            breakdown['ingredients'].append({
                'name': 'Egg',
                'quantity': f'{egg_count} piece',
                'package_price': float(egg.price),
                'package_size': f'{egg.unit}',
                'price_per_unit': price_per_piece,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    white_sugar = get_ingredient_price('White Sugar')
    if white_sugar:
        price_per_g = white_sugar.get_price_per_gram()
        if price_per_g:
            cost = white_sugar_g * price_per_g
            breakdown['ingredients'].append({
                'name': 'White Sugar',
                'quantity': f'{white_sugar_g}g',
                'package_price': float(white_sugar.price),
                'package_size': f'{white_sugar.unit}',
                'price_per_unit': price_per_g,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    brown_sugar = get_ingredient_price('Brown Sugar')
    if brown_sugar:
        price_per_g = brown_sugar.get_price_per_gram()
        if price_per_g:
            cost = brown_sugar_g * price_per_g
            breakdown['ingredients'].append({
                'name': 'Brown Sugar',
                'quantity': f'{brown_sugar_g}g',
                'package_price': float(brown_sugar.price),
                'package_size': f'{brown_sugar.unit}',
                'price_per_unit': price_per_g,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    vanilla = get_ingredient_price('Vanilla Essence')
    if vanilla:
        price_per_ml = vanilla.get_price_per_ml()
        if price_per_ml:
            cost = vanilla_essence_ml * price_per_ml
            breakdown['ingredients'].append({
                'name': 'Vanilla Essence',
                'quantity': f'{vanilla_essence_ml}ml',
                'package_price': float(vanilla.price),
                'package_size': f'{vanilla.unit}',
                'price_per_unit': price_per_ml,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    maida = get_ingredient_price('Maida/Ragi')
    if maida:
        price_per_g = maida.get_price_per_gram()
        if price_per_g:
            cost = maida_ragi_g * price_per_g
            breakdown['ingredients'].append({
                'name': 'Maida/Ragi',
                'quantity': f'{maida_ragi_g}g',
                'package_price': float(maida.price),
                'package_size': f'{maida.unit}',
                'price_per_unit': price_per_g,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    # Variety-specific compound
    variety_lower = variety_name.lower()
    if 'mango' in variety_lower:
        compound = get_ingredient_price('Mango Compound')
        compound_name = 'Mango Compound'
    elif 'strawberry' in variety_lower:
        compound = get_ingredient_price('Strawberry Compound')
        compound_name = 'Strawberry Compound'
    elif 'pineapple' in variety_lower:
        compound = get_ingredient_price('Pineapple Compound')
        compound_name = 'Pineapple Compound'
    elif 'pista' in variety_lower:
        compound = get_ingredient_price('Pista Compound')
        compound_name = 'Pista Compound'
    elif 'ragi' in variety_lower:
        # Ragi brownie uses dark compound
        compound = get_ingredient_price('Dark Compound')
        compound_name = 'Dark Compound'
    else:
        compound = get_ingredient_price('Dark Compound')
        compound_name = 'Dark Compound'
    
    if compound:
        price_per_g = compound.get_price_per_gram()
        if price_per_g:
            cost = compound_g * price_per_g
            breakdown['ingredients'].append({
                'name': compound_name,
                'quantity': f'{compound_g}g',
                'package_price': float(compound.price),
                'package_size': f'{compound.unit}',
                'price_per_unit': price_per_g,
                'cost': cost
            })
            breakdown['total_cost_16_brownies'] += cost
    
    # Pista nuts (only for Pista Brownie)
    if 'pista' in variety_lower:
        pista_nuts = get_ingredient_price('Pista Nuts')
        if pista_nuts:
            price_per_g = pista_nuts.get_price_per_gram()
            if price_per_g:
                cost = 16 * price_per_g
                breakdown['ingredients'].append({
                    'name': 'Pista Nuts',
                    'quantity': '16g',
                    'package_price': float(pista_nuts.price),
                    'package_size': f'{pista_nuts.unit}',
                    'price_per_unit': price_per_g,
                    'cost': cost
                })
                breakdown['total_cost_16_brownies'] += cost
    
    # Milk compound and white compound (only for Ragi Brownie)
    if 'ragi' in variety_lower:
        milk_compound = get_ingredient_price('Milk Compound')
        if milk_compound:
            price_per_g = milk_compound.get_price_per_gram()
            if price_per_g:
                cost = 25 * price_per_g
                breakdown['ingredients'].append({
                    'name': 'Milk Compound',
                    'quantity': '25g',
                    'package_price': float(milk_compound.price),
                    'package_size': f'{milk_compound.unit}',
                    'price_per_unit': price_per_g,
                    'cost': cost
                })
                breakdown['total_cost_16_brownies'] += cost
        
        white_compound = get_ingredient_price('White Compound')
        if white_compound:
            price_per_g = white_compound.get_price_per_gram()
            if price_per_g:
                cost = 25 * price_per_g
                breakdown['ingredients'].append({
                    'name': 'White Compound',
                    'quantity': '25g',
                    'package_price': float(white_compound.price),
                    'package_size': f'{white_compound.unit}',
                    'price_per_unit': price_per_g,
                    'cost': cost
                })
                breakdown['total_cost_16_brownies'] += cost
    
    # Fixed costs
    oven_charges = get_ingredient_price('Oven Charges')
    if oven_charges:
        price_per_batch = oven_charges.get_price_per_piece()
        if price_per_batch:
            breakdown['ingredients'].append({
                'name': 'Oven Charges',
                'quantity': '16 brownies',
                'package_price': float(oven_charges.price),
                'package_size': f'{oven_charges.unit}',
                'price_per_unit': price_per_batch,
                'cost': price_per_batch
            })
            breakdown['total_cost_16_brownies'] += price_per_batch
    
    miscellaneous = get_ingredient_price('Miscellaneous')
    if miscellaneous:
        price_per_batch = miscellaneous.get_price_per_piece()
        if price_per_batch:
            breakdown['ingredients'].append({
                'name': 'Miscellaneous',
                'quantity': '16 brownies',
                'package_price': float(miscellaneous.price),
                'package_size': f'{miscellaneous.unit}',
                'price_per_unit': price_per_batch,
                'cost': price_per_batch
            })
            breakdown['total_cost_16_brownies'] += price_per_batch
    
    # Add packing cost (₹1.8 per brownie × 16 = ₹28.8 for 16 brownies)
    packing = get_ingredient_price('Packing')
    packing_cost = 28.8  # Default value
    if packing:
        price_per_batch = packing.get_price_per_piece()
        if price_per_batch:
            packing_cost = price_per_batch
            breakdown['ingredients'].append({
                'name': 'Packing',
                'quantity': '16 brownies (₹1.8 per brownie)',
                'package_price': float(packing.price),
                'package_size': f'{packing.unit}',
                'price_per_unit': price_per_batch,
                'cost': price_per_batch
            })
    else:
        # Fallback: Add packing cost directly if not in database
        breakdown['ingredients'].append({
            'name': 'Packing',
            'quantity': '16 brownies (₹1.8 per brownie)',
            'package_price': 28.8,
            'package_size': '16 brownies',
            'price_per_unit': 28.8,
            'cost': 28.8
        })
    breakdown['total_cost_16_brownies'] += packing_cost
    
    # Add transportation cost (₹20 for 16 brownies)
    transportation = get_ingredient_price('Transportation')
    transportation_cost = 20.0  # Default value
    if transportation:
        price_per_batch = transportation.get_price_per_piece()
        if price_per_batch:
            transportation_cost = price_per_batch
            breakdown['ingredients'].append({
                'name': 'Transportation',
                'quantity': '16 brownies',
                'package_price': float(transportation.price),
                'package_size': f'{transportation.unit}',
                'price_per_unit': price_per_batch,
                'cost': price_per_batch
            })
    else:
        # Fallback: Add transportation cost directly if not in database
        breakdown['ingredients'].append({
            'name': 'Transportation',
            'quantity': '16 brownies',
            'package_price': 20.0,
            'package_size': '16 brownies',
            'price_per_unit': 20.0,
            'cost': 20.0
        })
    breakdown['total_cost_16_brownies'] += transportation_cost
    
    # Add variety miscellaneous cost (₹1 per brownie × 16 = ₹16 for 16 brownies)
    variety_misc_cost = 16.0  # ₹1 per brownie
    breakdown['ingredients'].append({
        'name': 'Variety Miscellaneous Cost',
        'quantity': '16 brownies (₹1 per brownie)',
        'package_price': 16.0,
        'package_size': '16 brownies',
        'price_per_unit': 1.0,
        'cost': variety_misc_cost
    })
    breakdown['total_cost_16_brownies'] += variety_misc_cost
    
    breakdown['cost_per_brownie'] = breakdown['total_cost_16_brownies'] / 16.0
    
    return breakdown


def calculate_brownies_from_price(price):
    """
    Calculate number of brownies based on price per unit.
    
    Rules:
    1. If price < 15: 0.5 brownie
    2. If price 25-35: 1 brownie
    3. If price 40-55: 1.33 brownie
    4. If price >= 160: kg-based calculation
       a. 160-190: 4 brownies
       b. 300-380: 8 brownies
       c. 400-490: 12 brownies
       d. 500-620: 16 brownies
       e. > 620: divide by 500, multiply by 16
    5. Otherwise (15-25, 35-40, 55-160): 1 brownie (default)
    """
    price_float = float(price)
    
    # Rule 1: Price < 15 → 0.5 brownie
    if price_float < 15:
        return 0.5
    
    # Rule 4: Price >= 160 → kg-based calculation
    if price_float >= 160:
        # Rule 4e: If price > 620, divide by 500 and apply 16 brownies per 500
        if price_float > 620:
            multiplier = price_float / 500.0
            return multiplier * 16.0
        # Rule 4d: 500-620 → 16 brownies
        elif 500 <= price_float <= 620:
            return 16.0
        # Rule 4c: 400-490 → 12 brownies
        elif 400 <= price_float <= 490:
            return 12.0
        # Rule 4b: 300-380 → 8 brownies
        elif 300 <= price_float <= 380:
            return 8.0
        # Rule 4a: 160-190 → 4 brownies
        elif 160 <= price_float <= 190:
            return 4.0
        # Default for kg-based (190-300): treat as 4 brownies (conservative)
        else:
            return 4.0
    
    # Rule 3: Price 40-55 → 1.33 brownie
    if 40 <= price_float <= 55:
        return 1.33
    
    # Rule 2: Price 25-35 → 1 brownie
    if 25 <= price_float <= 35:
        return 1.0
    
    # Default: 1 brownie (for 15-25, 35-40, 55-160)
    return 1.0


def calculate_total_cost_and_profit(orders):
    """Calculate total ingredient cost and profit for a list of orders"""
    if IngredientPrice is None:
        # Fallback to 30% margin if ingredient prices not available
        total_sales = sum(float(order.price * max(0, (order.quantity or 0) - (order.returns or 0))) for order in orders)
        return total_sales * 0.30, total_sales * 0.30
    
    total_cost = 0
    total_sales = 0
    
    for order in orders:
        variety = order.variety
        variety_name = variety.name if variety else 'Classic Brownie'
        
        # Calculate effective quantity (quantity - returns)
        effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
        
        # Calculate cost per brownie for this variety using get_cost_breakdown (same as ingredients page)
        breakdown = get_cost_breakdown(variety_name)
        cost_per_brownie = breakdown.get('cost_per_brownie') if breakdown else None
        
        if cost_per_brownie is None:
            continue
        
        # For combo packs, cost_per_brownie is actually cost per combo pack
        variety = order.variety
        if variety and variety.is_combo_pack():
            # For combo packs, cost_per_brownie is already the total cost of one combo pack
            # So we multiply directly by effective quantity (number of combo packs)
            total_cost += cost_per_brownie * effective_quantity
            # For sales, always use actual order.price from database (sum of all order prices)
            total_sales += float(order.price * effective_quantity)
        else:
            # For regular brownies, determine brownie count based on price
            order_price = float(order.price)
            order_quantity = float(effective_quantity)
            
            brownies_per_unit = calculate_brownies_from_price(order_price)
            brownies_count = brownies_per_unit * order_quantity
            total_cost += brownies_count * cost_per_brownie
            total_sales += float(order.price * effective_quantity)
    
    # Subtract total courier costs from profit
    total_courier = sum(float(order.courier_price) if order.courier_price else 0.0 for order in orders)
    
    profit = total_sales - total_cost - total_courier
    return profit, total_cost


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
        returns = request.form.get('returns', type=int) or 0
        price = request.form.get('price', type=float)
        delivery_date_str = request.form.get('delivery_date')
        payment_status = request.form.get('payment_status', 'unpaid')
        paid_amount = request.form.get('paid_amount', type=float) or 0
        courier_price = request.form.get('courier_price', type=float) or 0
        
        # Validation
        if not variety_id or not shop_id or not quantity or not price or not delivery_date_str:
            flash('All fields are required', 'error')
            return redirect(url_for('index'))
        
        if quantity <= 0 or price <= 0:
            flash('Quantity and price must be positive numbers', 'error')
            return redirect(url_for('index'))
        
        if returns < 0 or returns > quantity:
            flash('Returns must be between 0 and quantity', 'error')
            return redirect(url_for('index'))
        
        # Calculate effective quantity (quantity - returns)
        effective_quantity = max(0, quantity - returns)
        
        # Validate payment status
        if payment_status not in ['paid', 'unpaid', 'partial']:
            payment_status = 'unpaid'
        
        # Validate paid amount based on effective quantity
        total_amount = float(price * effective_quantity)
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
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.add_order(
                variety_id,
                shop_id,
                quantity,
                Decimal(str(price)),
                delivery_date,
                payment_status,
                Decimal(str(paid_amount)),
                Decimal(str(courier_price)),
                returns
            )
            order_total = total_amount
        else:
            order = Order(
                variety_id=variety_id,
                shop_id=shop_id,
                quantity=quantity,
                returns=returns,
                price=Decimal(str(price)),
                delivery_date=delivery_date,
                payment_status=payment_status,
                paid_amount=Decimal(str(paid_amount)),
                courier_price=Decimal(str(courier_price))
            )
            db_session.add(order)
            db_session.commit()
            order_total = float(order.price * effective_quantity)
        
        flash(f'Order added successfully! Total: ₹{order_total:.2f}', 'success')
        return redirect(url_for('index'))
    
    except Exception as e:
        db_session.rollback()
        flash(f'Error adding order: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/varieties')
def varieties():
    """List and manage varieties"""
    varieties_list = Variety.query.order_by(Variety.name).all()
    # Get all varieties for combo pack selection (exclude combo packs themselves)
    all_varieties = [v for v in varieties_list if not v.is_combo_pack()]
    return render_template('varieties.html', varieties=varieties_list, all_varieties=all_varieties)


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
        
        # Prepare combo pack config (JSON string of variety items with quantities)
        import json
        combo_pack_config = None
        combo_items = []
        
        # Get all variety IDs from form
        all_varieties = Variety.query.all()
        for var in all_varieties:
            if not var.is_combo_pack():  # Don't include combo packs in combo packs
                qty_key = f'combo_qty_{var.id}'
                quantity = request.form.get(qty_key, type=int)
                if quantity and quantity > 0:
                    combo_items.append({"id": var.id, "quantity": quantity})
        
        # Get extra packing cost from form (default to 5.0)
        extra_packing_cost = request.form.get('extra_packing_cost', type=float) or 5.0
        
        # Set combo_pack_config to empty string if no items, or JSON object with items and cost
        if combo_items:
            combo_pack_config = json.dumps({
                "items": combo_items,
                "extra_packing_cost": extra_packing_cost
            })
        else:
            combo_pack_config = ''  # Empty string for regular variety
        
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.add_variety(name, Decimal(str(default_price)), combo_pack_config)
        else:
            variety = Variety(name=name, default_price=Decimal(str(default_price)), 
                            combo_pack_config=combo_pack_config)
            db_session.add(variety)
            db_session.commit()
        
        flash(f'Variety "{name}" added successfully', 'success')
        return redirect(url_for('varieties'))
    
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
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
        
        # Prepare combo pack config (JSON string with items and extra_packing_cost)
        import json
        combo_items = []
        
        # Get all variety IDs from form
        all_varieties = Variety.query.all()
        for var in all_varieties:
            if not var.is_combo_pack():  # Don't include combo packs in combo packs
                qty_key = f'combo_qty_{var.id}'
                quantity = request.form.get(qty_key, type=int)
                if quantity and quantity > 0:
                    combo_items.append({"id": var.id, "quantity": quantity})
        
        # Get extra packing cost from form (default to 5.0)
        extra_packing_cost = request.form.get('extra_packing_cost', type=float) or 5.0
        
        # Set combo_pack_config to empty string if no items, or JSON object with items and cost
        if combo_items:
            combo_pack_config = json.dumps({
                "items": combo_items,
                "extra_packing_cost": extra_packing_cost
            })
        else:
            combo_pack_config = ''  # Empty string to clear combo pack config
        
        if USE_GOOGLE_SHEETS:
            # For Google Sheets, update via API
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_variety(id, name, Decimal(str(default_price)), combo_pack_config)
        else:
            # For SQLite, update the object and commit
            variety.name = name
            variety.default_price = Decimal(str(default_price))
            variety.combo_pack_config = combo_pack_config
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
            effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
            order_total = float(order.price * effective_quantity)
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
    # Get filter parameters
    shop_id_filter = request.args.get('shop_id', type=int)
    pending_only = request.args.get('pending_only', type=str) == 'true'
    
    # Get all shops for filter dropdown
    all_shops = Shop.query.order_by(Shop.name).all()
    
    # Get all orders ordered by delivery date (newest first)
    if shop_id_filter:
        # Filter orders by shop
        all_orders = Order.query.filter_by(shop_id=shop_id_filter).order_by(Order.delivery_date.desc(), Order.created_at.desc()).all()
        selected_shop = Shop.query.get(shop_id_filter)
    else:
        all_orders = Order.query.order_by(Order.delivery_date.desc(), Order.created_at.desc()).all()
        selected_shop = None
    
    # Filter by pending payments if requested
    if pending_only:
        filtered_orders = []
        for order in all_orders:
            effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
            order_total = float(order.price * effective_quantity)
            paid_amt = float(order.paid_amount) if order.paid_amount else 0
            pending_amt = order_total - paid_amt
            if pending_amt > 0:
                filtered_orders.append(order)
        all_orders = filtered_orders
    
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
        effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
        order_total = float(order.price * effective_quantity)
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
    
    # Timestamps are now stored in IST, so no offset needed
    return render_template('orders.html', months_grouped=months_grouped, total_sales=total_sales, total_pending=total_pending, total_orders=len(all_orders), all_shops=all_shops, selected_shop=selected_shop, shop_id_filter=shop_id_filter, pending_only=pending_only)


@app.route('/ingredients', methods=['GET', 'POST'])
def ingredients():
    """Ingredients cost management page"""
    if request.method == 'POST':
        try:
            # Update all ingredient prices
            ingredients_list = IngredientPrice.query.all()
            for ingredient in ingredients_list:
                price_key = f'price_{ingredient.id}'
                new_price = request.form.get(price_key, type=float)
                if new_price is not None and new_price >= 0:
                    if USE_GOOGLE_SHEETS:
                        # For Google Sheets, update via API
                        from google_sheets import get_gs_db
                        gs = get_gs_db()
                        gs.update_ingredient_price(
                            ingredient.id,
                            ingredient.name,
                            Decimal(str(new_price)),
                            ingredient.unit,
                            ingredient.package_size,
                            ingredient.package_unit
                        )
                    else:
                        # For SQLite, update the object and commit
                        ingredient.price = Decimal(str(new_price))
                        ingredient.updated_at = datetime.utcnow()
            
            if not USE_GOOGLE_SHEETS:
                db_session.commit()
            flash('Ingredient prices updated successfully!', 'success')
            return redirect(url_for('ingredients'))
        except Exception as e:
            if not USE_GOOGLE_SHEETS:
                db_session.rollback()
            flash(f'Error updating ingredient prices: {str(e)}', 'error')
    
    # GET request - show current prices
    ingredients_list = IngredientPrice.query.order_by(IngredientPrice.name).all()
    
    # Get cost breakdown for all varieties
    varieties = Variety.query.order_by(Variety.name).all()
    variety_breakdowns = {}
    variety_info = {}  # Store variety info to identify combo packs
    variety_id_to_name = {}  # Map variety IDs to names for display
    
    for variety in varieties:
        variety_id_to_name[variety.id] = variety.name
        breakdown = get_cost_breakdown(variety.name)
        if breakdown:
            variety_breakdowns[variety.name] = breakdown
            combo_items_display = []
            if variety.is_combo_pack():
                combo_items = variety.get_combo_pack_varieties()
                for item in combo_items:
                    if isinstance(item, dict):
                        var_id = item.get('id')
                        qty = item.get('quantity', 1)
                        var_name = variety_id_to_name.get(var_id, f'Variety {var_id}')
                        combo_items_display.append(f'{qty}x {var_name}')
                    else:
                        var_name = variety_id_to_name.get(item, f'Variety {item}')
                        combo_items_display.append(f'1x {var_name}')
            
            variety_info[variety.name] = {
                'is_combo_pack': variety.is_combo_pack(),
                'combo_pack_items_display': combo_items_display
            }
    
    return render_template('ingredients.html', ingredients=ingredients_list, variety_breakdowns=variety_breakdowns, variety_info=variety_info)


@app.route('/cost-breakdown', methods=['GET', 'POST'])
def cost_breakdown():
    """Cost breakdown page for brownie production costs"""
    # Get current month and year as default
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Get all available years and months for dropdown
    if USE_GOOGLE_SHEETS:
        all_orders = Order.query.all()
        years = sorted(set(order.delivery_date.year for order in all_orders if order.delivery_date), reverse=True)
    else:
        years = db.session.query(extract('year', Order.delivery_date).label('year')).distinct().order_by(text('year desc')).all()
        years = [int(y[0]) for y in years if y[0]]
    
    available_years = years if years else [current_year]
    
    # Handle POST request (calculate costs)
    if request.method == 'POST':
        try:
            # Get form data
            selected_year = request.form.get('year', type=int, default=current_year)
            selected_month = request.form.get('month', type=int, default=current_month)
            
            # Get ingredient prices
            egg_price_per_piece = request.form.get('egg_price', type=float, default=0)
            sugar_price_per_kg = request.form.get('sugar_price', type=float, default=0)
            brown_sugar_price_per_kg = request.form.get('brown_sugar_price', type=float, default=0)
            maida_price_per_kg = request.form.get('maida_price', type=float, default=0)
            
            # Get all orders for the selected month
            if USE_GOOGLE_SHEETS:
                all_orders = Order.query.all()
                orders = [
                    order for order in all_orders
                    if order.delivery_date and order.delivery_date.year == selected_year and order.delivery_date.month == selected_month
                ]
            else:
                orders = Order.query.filter(
                    extract('year', Order.delivery_date) == selected_year,
                    extract('month', Order.delivery_date) == selected_month
                ).all()
            
            # Calculate total brownies quantity for the month
            # Price rules:
            # - Prices >= 15 (including 25, 28, 32, 35) → count as 1 brownie per unit
            # - Prices < 15 → count as 0.5 brownie per unit
            # Example: price=25, quantity=2 → 2 brownies
            # Example: price=12.5, quantity=1 → 0.5 brownies
            # For combo packs: count actual brownies in the combo pack
            total_brownies = 0
            for order in orders:
                variety = order.variety
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                order_quantity = float(effective_quantity)
                
                # Check if this is a combo pack
                if variety and variety.is_combo_pack():
                    # For combo packs, count actual brownies in the combo pack
                    brownies_per_combo = get_brownies_in_combo_pack(variety)
                    brownies_for_order = brownies_per_combo * order_quantity
                else:
                    # For regular brownies, determine brownie count based on price
                    order_price = float(order.price)
                    brownies_per_unit = calculate_brownies_from_price(order_price)
                    brownies_for_order = brownies_per_unit * order_quantity
                
                total_brownies += brownies_for_order
            
            # Calculate quantities needed (per 4 brownies)
            # 1 egg for 4 brownies, 13g white sugar for 4 brownies, 13g brown sugar for 4 brownies, 30g maida/ragi for 4 brownies
            batches_of_4 = total_brownies / 4.0  # How many batches of 4 brownies
            
            total_eggs_needed = batches_of_4
            total_sugar_needed_kg = (batches_of_4 * 13) / 1000.0  # Convert grams to kg
            total_brown_sugar_needed_kg = (batches_of_4 * 13) / 1000.0  # Convert grams to kg
            total_maida_needed_kg = (batches_of_4 * 30) / 1000.0  # Convert grams to kg
            
            # Calculate costs
            egg_cost = total_eggs_needed * egg_price_per_piece
            sugar_cost = total_sugar_needed_kg * sugar_price_per_kg
            brown_sugar_cost = total_brown_sugar_needed_kg * brown_sugar_price_per_kg
            maida_cost = total_maida_needed_kg * maida_price_per_kg
            
            total_cost = egg_cost + sugar_cost + brown_sugar_cost + maida_cost
            
            # Prepare breakdown data
            breakdown = {
                'selected_year': selected_year,
                'selected_month': selected_month,
                'month_name': datetime(selected_year, selected_month, 1).strftime('%B %Y'),
                'total_brownies': total_brownies,
                'total_orders': len(orders),
                'egg': {
                    'quantity': total_eggs_needed,
                    'unit': 'pieces',
                    'price_per_unit': egg_price_per_piece,
                    'total_cost': egg_cost
                },
                'sugar': {
                    'quantity': total_sugar_needed_kg,
                    'unit': 'kg',
                    'price_per_unit': sugar_price_per_kg,
                    'total_cost': sugar_cost
                },
                'brown_sugar': {
                    'quantity': total_brown_sugar_needed_kg,
                    'unit': 'kg',
                    'price_per_unit': brown_sugar_price_per_kg,
                    'total_cost': brown_sugar_cost
                },
                'maida': {
                    'quantity': total_maida_needed_kg,
                    'unit': 'kg',
                    'price_per_unit': maida_price_per_kg,
                    'total_cost': maida_cost
                },
                'total_cost': total_cost
            }
            
            return render_template('cost_breakdown.html',
                                 current_month=current_month,
                                 current_year=current_year,
                                 available_years=available_years,
                                 selected_year=selected_year,
                                 selected_month=selected_month,
                                 egg_price=egg_price_per_piece,
                                 sugar_price=sugar_price_per_kg,
                                 brown_sugar_price=brown_sugar_price_per_kg,
                                 maida_price=maida_price_per_kg,
                                 breakdown=breakdown)
        
        except Exception as e:
            flash(f'Error calculating costs: {str(e)}', 'error')
    
    # GET request - show form
    return render_template('cost_breakdown.html',
                         current_month=current_month,
                         current_year=current_year,
                         available_years=available_years,
                         selected_year=current_year,
                         selected_month=current_month,
                         breakdown=None)


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
        
        # Calculate totals using effective quantity (with Combo Pack 1 price correction)
        total_sales = sum(float(order.price * max(0, (order.quantity or 0) - (order.returns or 0))) for order in orders)
        total_paid = sum(float(order.paid_amount) if order.paid_amount else 0 for order in orders)
        total_pending = total_sales - total_paid
        margin, total_cost = calculate_total_cost_and_profit(orders)
        profit_percentage = (margin / total_sales * 100) if total_sales > 0 else 0
        
        # Shop-wise breakdown with pending amounts (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets
            shop_dict = {}
            for order in orders:
                shop = order.shop
                shop_name = shop.name if shop else 'Unknown'
                if shop_name not in shop_dict:
                    shop_dict[shop_name] = {'total': 0, 'paid': 0}
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                shop_dict[shop_name]['total'] += float(order.price * effective_quantity)
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
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                variety_dict[variety_name] += float(order.price * effective_quantity)
            
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
        
        # Variety-wise cost breakdown
        variety_cost_breakdown = {}
        for order in orders:
            variety = order.variety
            variety_name = variety.name if variety else 'Unknown'
            
            if variety_name not in variety_cost_breakdown:
                variety_cost_breakdown[variety_name] = {
                    'sales': 0,
                    'cost': 0,
                    'quantity': 0,
                    'brownies_count': 0
                }
            
            # Calculate cost per brownie for this variety using get_cost_breakdown (same as ingredients page)
            breakdown = get_cost_breakdown(variety_name)
            cost_per_brownie = breakdown.get('cost_per_brownie') if breakdown else None
            
            if cost_per_brownie is not None:
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                order_quantity = float(effective_quantity)
                
                # For combo packs, cost_per_brownie is actually cost per combo pack
                if variety and variety.is_combo_pack():
                    # For Combo Pack 1, cost_per_brownie is already the total cost of one combo pack
                    # So we multiply directly by effective quantity (number of combo packs)
                    order_cost = cost_per_brownie * effective_quantity
                    # For sales, always use actual order.price from database (not calculated price)
                    order_sales = float(order.price * effective_quantity)
                    # For combo pack, count actual brownies in the combo pack
                    brownies_per_combo = get_brownies_in_combo_pack(variety)
                    brownies_count = brownies_per_combo * effective_quantity
                else:
                    # For regular brownies, determine brownie count based on price
                    order_price = float(order.price)
                    brownies_per_unit = calculate_brownies_from_price(order_price)
                    brownies_count = brownies_per_unit * order_quantity
                    order_cost = brownies_count * cost_per_brownie
                    order_sales = float(order.price * effective_quantity)
                
                variety_cost_breakdown[variety_name]['sales'] += order_sales
                variety_cost_breakdown[variety_name]['cost'] += order_cost
                variety_cost_breakdown[variety_name]['quantity'] += order_quantity
                variety_cost_breakdown[variety_name]['brownies_count'] += brownies_count
        
        # Format variety breakdown with costs
        variety_breakdown = []
        for variety_name, data in variety_cost_breakdown.items():
            profit = data['sales'] - data['cost']
            profit_pct = (profit / data['sales'] * 100) if data['sales'] > 0 else 0
            # For combo packs, show cost per combo pack, not per brownie
            variety_obj = Variety.query.filter_by(name=variety_name).first()
            if variety_obj and variety_obj.is_combo_pack():
                cost_per_unit = round(data['cost'] / data['quantity'], 2) if data['quantity'] > 0 else 0
            else:
                cost_per_unit = round(data['cost'] / data['brownies_count'], 2) if data['brownies_count'] > 0 else 0
            variety_breakdown.append({
                'name': variety_name,
                'sales': round(data['sales'], 2),
                'cost': round(data['cost'], 2),
                'profit': round(profit, 2),
                'profit_percentage': round(profit_pct, 2),
                'quantity': data['quantity'],
                'brownies_count': round(data['brownies_count'], 2),
                'cost_per_brownie': cost_per_unit
            })
        
        # Sort by sales descending
        variety_breakdown.sort(key=lambda x: x['sales'], reverse=True)
        
        # Summary statistics
        total_orders = len(orders)
        avg_order_value = total_sales / total_orders if total_orders > 0 else 0
        
        return jsonify({
            'total_sales': round(total_sales, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_pending, 2),
            'margin': round(margin, 2),
            'profit_percentage': round(profit_percentage, 2),
            'total_cost': round(total_cost, 2),
            'shop_data': shop_data,
            'variety_data': variety_data,
            'variety_breakdown': variety_breakdown,
            'total_orders': total_orders,
            'avg_order_value': round(avg_order_value, 2)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/profit-by-month')
def api_profit_by_month():
    """JSON API endpoint for profit by month data"""
    try:
        # Get all orders
        if USE_GOOGLE_SHEETS:
            all_orders = Order.query.all()
        else:
            all_orders = Order.query.all()
        
        # Group orders by month
        monthly_data = {}
        
        for order in all_orders:
            if not order.delivery_date:
                continue
                
            month_key = order.delivery_date.strftime('%Y-%m')
            month_label = order.delivery_date.strftime('%B %Y')
            
            effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    'label': month_label,
                    'orders': [],
                    'sales': 0,
                    'cost': 0
                }
            
            monthly_data[month_key]['orders'].append(order)
            monthly_data[month_key]['sales'] += float(order.price * effective_quantity)
        
        # Calculate profit for each month
        profit_by_month = []
        for month_key in sorted(monthly_data.keys()):
            month_info = monthly_data[month_key]
            orders = month_info['orders']
            
            # Calculate total cost and profit
            margin, total_cost = calculate_total_cost_and_profit(orders)
            
            profit_by_month.append({
                'month': month_info['label'],
                'month_key': month_key,
                'profit': round(margin, 2),
                'sales': round(month_info['sales'], 2),
                'cost': round(total_cost, 2)
            })
        
        return jsonify({
            'profit_by_month': profit_by_month
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
        
        # Calculate totals using effective quantity (with Combo Pack 1 price correction)
        total_sales = sum(float(order.price * max(0, (order.quantity or 0) - (order.returns or 0))) for order in orders)
        total_paid = sum(float(order.paid_amount) if order.paid_amount else 0 for order in orders)
        total_pending = total_sales - total_paid
        margin, total_cost = calculate_total_cost_and_profit(orders)
        profit_percentage = (margin / total_sales * 100) if total_sales > 0 else 0
        
        # Shop-wise breakdown with pending amounts (sorted by total descending)
        if USE_GOOGLE_SHEETS:
            # Group and aggregate in Python for Google Sheets (already filtered by month/year above)
            shop_dict = {}
            for order in orders:
                shop = order.shop
                shop_name = shop.name if shop else 'Unknown'
                if shop_name not in shop_dict:
                    shop_dict[shop_name] = {'total': 0, 'paid': 0}
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                shop_dict[shop_name]['total'] += float(order.price * effective_quantity)
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
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                variety_dict[variety_name] += float(order.price * effective_quantity)
            
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
        
        # Variety-wise cost breakdown
        variety_cost_breakdown = {}
        for order in orders:
            variety = order.variety
            variety_name = variety.name if variety else 'Unknown'
            
            if variety_name not in variety_cost_breakdown:
                variety_cost_breakdown[variety_name] = {
                    'sales': 0,
                    'cost': 0,
                    'quantity': 0,
                    'brownies_count': 0
                }
            
            # Calculate cost per brownie for this variety using get_cost_breakdown (same as ingredients page)
            breakdown = get_cost_breakdown(variety_name)
            cost_per_brownie = breakdown.get('cost_per_brownie') if breakdown else None
            
            if cost_per_brownie is not None:
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                order_quantity = float(effective_quantity)
                
                # For combo packs, cost_per_brownie is actually cost per combo pack
                if variety and variety.is_combo_pack():
                    # For combo packs, cost_per_brownie is already the total cost of one combo pack
                    # So we multiply directly by effective quantity (number of combo packs)
                    order_cost = cost_per_brownie * effective_quantity
                    # For sales, always use actual order.price from database (sum of all order prices)
                    order_sales = float(order.price * effective_quantity)
                    # For combo pack, count actual brownies in the combo pack
                    brownies_per_combo = get_brownies_in_combo_pack(variety)
                    brownies_count = brownies_per_combo * effective_quantity
                else:
                    # For regular brownies, determine brownie count based on price
                    order_price = float(order.price)
                    brownies_per_unit = calculate_brownies_from_price(order_price)
                    brownies_count = brownies_per_unit * order_quantity
                    order_cost = brownies_count * cost_per_brownie
                    order_sales = float(order.price * effective_quantity)
                
                variety_cost_breakdown[variety_name]['sales'] += order_sales
                variety_cost_breakdown[variety_name]['cost'] += order_cost
                variety_cost_breakdown[variety_name]['quantity'] += order_quantity
                variety_cost_breakdown[variety_name]['brownies_count'] += brownies_count
        
        # Format variety breakdown with costs
        variety_breakdown = []
        for variety_name, data in variety_cost_breakdown.items():
            profit = data['sales'] - data['cost']
            profit_pct = (profit / data['sales'] * 100) if data['sales'] > 0 else 0
            # For combo packs, show cost per combo pack, not per brownie
            variety_obj = Variety.query.filter_by(name=variety_name).first()
            if variety_obj and variety_obj.is_combo_pack():
                cost_per_unit = round(data['cost'] / data['quantity'], 2) if data['quantity'] > 0 else 0
            else:
                cost_per_unit = round(data['cost'] / data['brownies_count'], 2) if data['brownies_count'] > 0 else 0
            variety_breakdown.append({
                'name': variety_name,
                'sales': round(data['sales'], 2),
                'cost': round(data['cost'], 2),
                'profit': round(profit, 2),
                'profit_percentage': round(profit_pct, 2),
                'quantity': data['quantity'],
                'brownies_count': round(data['brownies_count'], 2),
                'cost_per_brownie': cost_per_unit
            })
        
        # Sort by sales descending
        variety_breakdown.sort(key=lambda x: x['sales'], reverse=True)
        
        # Summary statistics
        total_orders = len(orders)
        avg_order_value = total_sales / total_orders if total_orders > 0 else 0
        
        return jsonify({
            'total_sales': round(total_sales, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_pending, 2),
            'margin': round(margin, 2),
            'profit_percentage': round(profit_percentage, 2),
            'total_cost': round(total_cost, 2),
            'shop_data': shop_data,
            'variety_data': variety_data,
            'variety_breakdown': variety_breakdown,
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
        effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
        order_total = float(order.price * effective_quantity)
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


@app.route('/shops/<int:id>/invoice', methods=['GET', 'POST'])
def shop_invoice(id):
    """Generate invoice for a shop with date period filter"""
    shop = Shop.query.get_or_404(id)
    
    if request.method == 'GET':
        # Show form to select date range
        return render_template('invoice_form.html', shop=shop)
    
    # POST request - generate invoice
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    
    if not start_date_str or not end_date_str:
        flash('Please select both start and end dates', 'error')
        return redirect(url_for('shop_invoice', id=id))
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            flash('Start date must be before or equal to end date', 'error')
            return redirect(url_for('shop_invoice', id=id))
    except ValueError:
        flash('Invalid date format', 'error')
        return redirect(url_for('shop_invoice', id=id))
    
    # Get all orders for this shop within the date range
    if USE_GOOGLE_SHEETS:
        all_orders = Order.query.filter_by(shop_id=id).all()
        # Filter by date range
        filtered_orders = []
        for order in all_orders:
            if order.delivery_date:
                # Handle both date and datetime objects
                if hasattr(order.delivery_date, 'date'):
                    order_date = order.delivery_date.date()
                else:
                    order_date = order.delivery_date
                if start_date <= order_date <= end_date:
                    filtered_orders.append(order)
        # Sort by delivery date (newest first)
        filtered_orders.sort(key=lambda x: x.delivery_date if x.delivery_date else date.min, reverse=True)
    else:
        from sqlalchemy import and_
        filtered_orders = Order.query.filter(
            and_(
                Order.shop_id == id,
                Order.delivery_date >= start_date,
                Order.delivery_date <= end_date
            )
        ).order_by(Order.delivery_date.desc()).all()
    
    # Process orders for invoice
    invoice_orders = []
    total_amount = 0
    total_paid = 0
    total_pending = 0
    
    for order in filtered_orders:
        effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
        order_total = float(order.price * effective_quantity)
        paid_amt = float(order.paid_amount) if order.paid_amount else 0
        pending_amt = order_total - paid_amt
        
        invoice_orders.append({
            'order': order,
            'total': order_total,
            'paid': paid_amt,
            'pending': pending_amt
        })
        total_amount += order_total
        total_paid += paid_amt
        total_pending += pending_amt
    
    invoice_date = datetime.now()
    return render_template('invoice.html', 
                         shop=shop, 
                         invoice_orders=invoice_orders, 
                         total_amount=total_amount,
                         total_paid=total_paid,
                         total_pending=total_pending,
                         invoice_date=invoice_date,
                         start_date=start_date,
                         end_date=end_date)


@app.route('/orders/edit/<int:id>', methods=['GET', 'POST'])
def edit_order(id):
    """Edit an existing order"""
    order = Order.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            variety_id = request.form.get('variety_id', type=int)
            shop_id = request.form.get('shop_id', type=int)
            quantity = request.form.get('quantity', type=int)
            returns = request.form.get('returns', type=int) or 0
            price = request.form.get('price', type=float)
            delivery_date_str = request.form.get('delivery_date')
            payment_status = request.form.get('payment_status', default='unpaid')
            paid_amount = request.form.get('paid_amount', type=float, default=0.00)
            courier_price = request.form.get('courier_price', type=float, default=0.00)
            
            # Validation
            if not variety_id or not shop_id or not quantity or not price or not delivery_date_str:
                flash('All fields are required', 'error')
                return redirect(url_for('edit_order', id=id))
            
            if quantity <= 0 or price <= 0:
                flash('Quantity and price must be positive numbers', 'error')
                return redirect(url_for('edit_order', id=id))
            
            if returns < 0 or returns > quantity:
                flash('Returns must be between 0 and quantity', 'error')
                return redirect(url_for('edit_order', id=id))
            
            # Calculate effective quantity (quantity - returns)
            effective_quantity = max(0, quantity - returns)
            
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
                    Decimal(str(paid_amount)),
                    Decimal(str(courier_price)),
                    returns
                )
                total = float(Decimal(str(price)) * effective_quantity)
            else:
                # For SQLite, update the object and commit
                order.variety_id = variety_id
                order.shop_id = shop_id
                order.quantity = quantity
                order.returns = returns
                order.price = Decimal(str(price))
                order.delivery_date = delivery_date
                order.payment_status = payment_status
                order.paid_amount = Decimal(str(paid_amount))
                order.courier_price = Decimal(str(courier_price))
                db_session.commit()
                total = float(order.price * effective_quantity)
            
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


@app.route('/orders/mark-paid/<int:id>', methods=['POST'])
def mark_order_paid(id):
    """Mark an order as paid with one click"""
    try:
        order = Order.query.get_or_404(id)
        
        # Calculate effective quantity (quantity - returns)
        effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
        
        # Calculate total amount based on effective quantity
        total_amount = float(order.price * effective_quantity)
        
        # Update payment status to paid
        if USE_GOOGLE_SHEETS:
            # For Google Sheets, update via API
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_order(
                id,
                order.variety_id,
                order.shop_id,
                order.quantity,
                order.price,
                order.delivery_date,
                'paid',
                Decimal(str(total_amount)),
                order.courier_price or 0,
                order.returns or 0
            )
        else:
            # For SQLite, update the object and commit
            order.payment_status = 'paid'
            order.paid_amount = Decimal(str(total_amount))
            db_session.commit()
        
        flash(f'Order marked as paid! Amount: ₹{total_amount:.2f}', 'success')
        
        # Redirect back to orders page, preserving filters if present
        shop_id = request.form.get('shop_id', type=int)
        pending_only = request.form.get('pending_only', type=str) == 'true'
        redirect_args = {}
        if shop_id:
            redirect_args['shop_id'] = shop_id
        if pending_only:
            redirect_args['pending_only'] = 'true'
        return redirect(url_for('orders', **redirect_args))
    
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error marking order as paid: {str(e)}', 'error')
        shop_id = request.form.get('shop_id', type=int)
        if shop_id:
            return redirect(url_for('orders', shop_id=shop_id))
        return redirect(url_for('orders'))


@app.route('/orders/mark-all-paid/<int:shop_id>', methods=['POST'])
def mark_all_orders_paid(shop_id):
    """Mark all unpaid/partial orders for a shop as paid"""
    try:
        shop = Shop.query.get_or_404(shop_id)
        
        # Get all orders for this shop that are not fully paid
        all_orders = Order.query.filter_by(shop_id=shop_id).all()
        unpaid_orders = []
        total_amount = 0
        
        for order in all_orders:
            # Calculate effective quantity (quantity - returns)
            effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
            order_total = float(order.price * effective_quantity)
            paid_amt = float(order.paid_amount) if order.paid_amount else 0
            pending_amt = order_total - paid_amt
            
            if pending_amt > 0:  # Only mark unpaid or partially paid orders
                unpaid_orders.append(order)
                total_amount += order_total
        
        if not unpaid_orders:
            flash(f'All orders for {shop.name} are already paid!', 'info')
            return redirect(url_for('orders', shop_id=shop_id))
        
        # Mark all unpaid orders as paid
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            for order in unpaid_orders:
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                order_total = float(order.price * effective_quantity)
                gs.update_order(
                    order.id,
                    order.variety_id,
                    order.shop_id,
                    order.quantity,
                    order.price,
                    order.delivery_date,
                    'paid',
                    Decimal(str(order_total)),
                    order.courier_price or 0,
                    order.returns or 0
                )
        else:
            for order in unpaid_orders:
                effective_quantity = max(0, (order.quantity or 0) - (order.returns or 0))
                order_total = float(order.price * effective_quantity)
                order.payment_status = 'paid'
                order.paid_amount = Decimal(str(order_total))
            db_session.commit()
        
        flash(f'Marked {len(unpaid_orders)} order(s) as paid for {shop.name}! Total: ₹{total_amount:.2f}', 'success')
        return redirect(url_for('orders', shop_id=shop_id))
    
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error marking orders as paid: {str(e)}', 'error')
        return redirect(url_for('orders', shop_id=shop_id))


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


@app.route('/refresh-cache', methods=['POST'])
def refresh_cache():
    """Manually refresh Google Sheets cache"""
    if not USE_GOOGLE_SHEETS:
        flash('Cache refresh is only available when using Google Sheets', 'info')
        return redirect(request.referrer or url_for('index'))
    
    try:
        from google_sheets import get_gs_db
        gs = get_gs_db()
        gs.refresh_cache()  # Clear all cache
        flash('Cache refreshed successfully! The app will now fetch fresh data from Google Sheets.', 'success')
    except Exception as e:
        flash(f'Error refreshing cache: {str(e)}', 'error')
    
    return redirect(request.referrer or url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)

