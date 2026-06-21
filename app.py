from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from collections import defaultdict
import calendar
import json
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


def _normalize_combo_items_for_compare(items):
    """List of (variety_id, quantity) for stable comparison."""
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append((item.get('id'), int(item.get('quantity', 1))))
        else:
            out.append((item, 1))
    return out


def _variety_by_name_ci(name):
    """Find variety by case-insensitive name (Sheets often use 'Combo pack' vs 'Combo Pack')."""
    target = (name or '').strip().lower()
    if not target:
        return None
    for v in Variety.query.all():
        if (v.name or '').strip().lower() == target:
            return v
    return None


def _apply_standard_combo_pack_contents():
    """Set PCM/PCS combo packs to the standard brownie lineups; totals follow ingredient breakdown."""
    # Keys are lowercased; matches any casing on the variety row (e.g. Combo pack 3 - PCS).
    STANDARD_COMBO_LINEUPS = {
        'combo pack 1 - pcm': [
            'Pista Brownie',
            'Classic Brownie',
            'Mango Brownie',
        ],
        'combo pack 3 - pcs': [
            'Pineapple Brownie',
            'Classic Brownie',
            'Strawberry Brownie',
        ],
    }

    for combo in Variety.query.all():
        if not combo.is_combo_pack():
            continue
        combo_key = (combo.name or '').strip().lower()
        child_names = STANDARD_COMBO_LINEUPS.get(combo_key)
        if not child_names:
            continue

        resolved_items = []
        missing = []
        for child_name in child_names:
            v = _variety_by_name_ci(child_name)
            if v and not v.is_combo_pack():
                resolved_items.append({'id': v.id, 'quantity': 1})
            else:
                missing.append(child_name)
        if missing:
            print(
                f"⚠ Standard combo '{combo.name}' not updated — "
                f"create these varieties first: {', '.join(missing)}"
            )
            continue

        desired_seq = _normalize_combo_items_for_compare(resolved_items)
        current_seq = _normalize_combo_items_for_compare(combo.get_combo_pack_varieties())
        if current_seq == desired_seq:
            continue

        extra_packing = 5.0
        if combo.combo_pack_config:
            try:
                data = json.loads(combo.combo_pack_config)
                if isinstance(data, dict) and 'extra_packing_cost' in data:
                    extra_packing = float(data['extra_packing_cost'])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        new_config = json.dumps({
            'items': resolved_items,
            'extra_packing_cost': extra_packing,
        })

        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.update_variety(
                combo.id,
                combo.name,
                Decimal(str(combo.default_price)),
                new_config,
            )
        else:
            combo.combo_pack_config = new_config
            db_session.commit()
        print(f"✓ Updated '{combo.name}' contents: {', '.join(child_names)}")


def get_variety_list_price(variety):
    """Selling price for a variety.
    Always uses the stored default_price when it is positive.
    Falls back to computing from combo children only when default_price is 0 / unset."""
    if not variety:
        return 0.0
    stored = float(variety.default_price or 0)
    if stored > 0:
        return stored
    # Fallback for combo packs whose price has not been set yet
    if variety.is_combo_pack():
        total = 0.0
        for item in variety.get_combo_pack_varieties():
            vid = item.get('id')
            qty = int(item.get('quantity', 1))
            child = Variety.query.get(vid)
            if child and not child.is_combo_pack():
                total += float(child.default_price or 0) * qty
        total += float(variety.get_extra_packing_cost())
        return round(total, 2)
    return stored


def variety_list_prices_map(varieties_seq):
    """Map variety id -> list price (computed for combos)."""
    return {v.id: get_variety_list_price(v) for v in varieties_seq}


def _sync_combo_pack_default_prices_from_config():
    """No-op: combo variety prices are now set manually by the user and must not be overwritten."""
    pass


def _ensure_cookie_varieties():
    """Create the four cookie varieties if they don't already exist.

    Default (selling) prices are placeholders the user can edit on the Varieties page;
    the cookie COST is computed separately by cookie_cost_breakdown()."""
    cookie_defaults = [
        ('Choco Chip Cookie - 1pc', 15),
        ('Choco Chip Cookie - 1 Box (5Pcs)', 75),
        ('Red Velvet Cookie - 1pc', 20),
        ('Red Velvet Cookie - 1 Box (5Pcs)', 100),
    ]
    existing_names = {(v.name or '').strip().lower() for v in Variety.query.all()}
    for name, price in cookie_defaults:
        if name.strip().lower() in existing_names:
            continue
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.add_variety(name, Decimal(str(price)))
        else:
            db_session.add(Variety(name=name, default_price=Decimal(str(price))))
        print(f"✓ Created cookie variety '{name}' (default price ₹{price})")
    if not USE_GOOGLE_SHEETS:
        db_session.commit()


def _ensure_chocolate_ingredients():
    """Ensure Dark/White Chocolate ingredient rows exist (used by cookie recipes)."""
    if IngredientPrice is None:
        return
    choc_defaults = [
        ('Dark Chocolate', 165),
        ('White Chocolate', 200),
    ]
    for name, price in choc_defaults:
        existing = IngredientPrice.query.filter_by(name=name).first()
        if existing:
            continue
        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.add_ingredient_price(name, Decimal(str(price)), '500g', Decimal('500'), 'g')
        else:
            db_session.add(IngredientPrice(
                name=name,
                price=Decimal(str(price)),
                unit='500g',
                package_size=Decimal('500'),
                package_unit='g'
            ))
        print(f"✓ Created ingredient '{name}' (₹{price}/500g)")
    if not USE_GOOGLE_SHEETS:
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
        _ensure_chocolate_ingredients()
        _ensure_cookie_varieties()
        _apply_standard_combo_pack_contents()
        _sync_combo_pack_default_prices_from_config()
else:
    db.init_app(app)
    # Initialize Google Sheets (this will also initialize ingredient prices)
    with app.app_context():
        db.create_all()
        # Update Miscellaneous cost if needed
        _update_miscellaneous_cost()
        _ensure_chocolate_ingredients()
        _ensure_cookie_varieties()
        _apply_standard_combo_pack_contents()
        _sync_combo_pack_default_prices_from_config()


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
        {'name': 'Dark Chocolate', 'price': 165, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
        {'name': 'White Chocolate', 'price': 200, 'unit': '500g', 'package_size': 500, 'package_unit': 'g'},
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


# Cookie recipe constants (Choco Chip / Red Velvet cookies)
COOKIE_BATCH_YIELD = 13      # cookies produced per batch
COOKIE_BOX_COUNT = 5         # cookies per box
COOKIE_BOX_PACKING = 7.0     # ₹ packing per box


def is_cookie(variety_name):
    """Cookies use a dedicated per-unit recipe instead of the brownie price-derived model."""
    return 'cookie' in (variety_name or '').strip().lower()


def _is_cookie_box(variety_name):
    """A cookie box is a 5-piece pack (name contains 'box')."""
    return 'box' in (variety_name or '').strip().lower()


def cookie_cost_breakdown(variety_name):
    """Per-unit cookie cost. A batch yields 13 cookies.

    Choco Chip (per batch of 13): butter 113g, white sugar 90g, brown sugar 90g,
    maida 180g, 1 egg, ₹1 vanilla, ₹2 misc, dark chocolate 40g.
    Red Velvet (per batch): base (no dark chocolate) + ₹25 cocoa + ₹2 red velvet essence
    + ₹2 extra misc + white chocolate 40g.
    Box (5pc): single cookie cost × 5 + ₹7 packing.

    Returns a breakdown dict whose 'cost_per_brownie' is the per-unit cost
    (per single cookie, or per box for box varieties)."""
    is_red_velvet = 'red velvet' in (variety_name or '').strip().lower()

    breakdown = {
        'variety': variety_name,
        'ingredients': [],
        'total_cost_16_brownies': 0,
        'cost_per_brownie': 0,
    }

    def add_ing(name, qty_label, package_price, package_size, price_per_unit, cost):
        breakdown['ingredients'].append({
            'name': name,
            'quantity': qty_label,
            'package_price': package_price,
            'package_size': package_size,
            'price_per_unit': price_per_unit,
            'cost': cost,
        })

    batch_label = f'batch of {COOKIE_BATCH_YIELD}'
    batch_total = 0.0

    # Weight-based ingredients sourced from ingredient prices
    weight_items = [
        ('Butter', 113),
        ('White Sugar', 90),
        ('Brown Sugar', 90),
        ('Maida/Ragi', 180),
    ]
    for ing_name, grams in weight_items:
        ing = get_ingredient_price(ing_name)
        if ing:
            ppg = ing.get_price_per_gram()
            if ppg:
                cost = grams * ppg
                batch_total += cost
                add_ing(ing_name, f'{grams}g ({batch_label})', float(ing.price), f'{ing.unit}', ppg, cost)

    # Egg (count-based)
    egg = get_ingredient_price('Egg')
    if egg:
        ppc = egg.get_price_per_piece()
        if ppc:
            cost = 1 * ppc
            batch_total += cost
            add_ing('Egg', f'1 piece ({batch_label})', float(egg.price), f'{egg.unit}', ppc, cost)

    # Flat per-batch costs
    vanilla_cost = 1.0
    batch_total += vanilla_cost
    add_ing('Vanilla Essence', f'flat ({batch_label})', vanilla_cost, '1 batch', vanilla_cost, vanilla_cost)

    misc_cost = 2.0
    batch_total += misc_cost
    add_ing('Miscellaneous', f'flat ({batch_label})', misc_cost, '1 batch', misc_cost, misc_cost)

    # Chocolate cost per gram, sourced from ingredient prices with a fallback to the
    # known 500g pack price if the ingredient row is not present.
    def _choc_per_gram(ing_name, fallback_500g_price):
        ing = get_ingredient_price(ing_name)
        if ing:
            ppg = ing.get_price_per_gram()
            if ppg:
                return ppg, float(ing.price), ing.unit
        return fallback_500g_price / 500.0, fallback_500g_price, '500g'

    if is_red_velvet:
        cocoa_cost = 25.0
        batch_total += cocoa_cost
        add_ing('Cocoa Powder', f'flat ({batch_label})', cocoa_cost, '1 batch', cocoa_cost, cocoa_cost)

        rv_essence_cost = 2.0
        batch_total += rv_essence_cost
        add_ing('Red Velvet Essence', f'flat ({batch_label})', rv_essence_cost, '1 batch', rv_essence_cost, rv_essence_cost)

        rv_extra_misc = 2.0
        batch_total += rv_extra_misc
        add_ing('Red Velvet Extra Misc', f'flat ({batch_label})', rv_extra_misc, '1 batch', rv_extra_misc, rv_extra_misc)

        # Red Velvet uses white chocolate (40g per batch) instead of dark chocolate
        wc_ppg, wc_pkg_price, wc_pkg = _choc_per_gram('White Chocolate', 200.0)
        wc_cost = 40 * wc_ppg
        batch_total += wc_cost
        add_ing('White Chocolate', f'40g ({batch_label})', wc_pkg_price, wc_pkg, wc_ppg, wc_cost)
    else:
        # Choco Chip uses dark chocolate (40g per batch)
        dc_ppg, dc_pkg_price, dc_pkg = _choc_per_gram('Dark Chocolate', 165.0)
        dc_cost = 40 * dc_ppg
        batch_total += dc_cost
        add_ing('Dark Chocolate', f'40g ({batch_label})', dc_pkg_price, dc_pkg, dc_ppg, dc_cost)

    single_cost = batch_total / COOKIE_BATCH_YIELD

    if _is_cookie_box(variety_name):
        add_ing('Single cookies × 5', f'{COOKIE_BOX_COUNT} cookies', round(single_cost, 4), '1 cookie', single_cost, single_cost * COOKIE_BOX_COUNT)
        add_ing('Box Packing', '1 box', COOKIE_BOX_PACKING, '1 box', COOKIE_BOX_PACKING, COOKIE_BOX_PACKING)
        per_unit = single_cost * COOKIE_BOX_COUNT + COOKIE_BOX_PACKING
    else:
        per_unit = single_cost

    breakdown['cost_per_brownie'] = per_unit
    breakdown['total_cost_16_brownies'] = per_unit
    return breakdown


def get_cost_breakdown(variety_name):
    """Get detailed cost breakdown for a variety showing how cost per brownie is calculated"""
    if IngredientPrice is None:
        return None

    # Cookies use a dedicated per-unit recipe (not the brownie price-derived model)
    if is_cookie(variety_name):
        return cookie_cost_breakdown(variety_name)
    
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
    
    variety_lower = variety_name.lower()
    
    # Ingredients needed for 16 brownies
    butter_g = 235
    egg_count = 4
    white_sugar_g = 52
    brown_sugar_g = 52
    vanilla_essence_ml = 4
    maida_ragi_g = 125
    compound_g = 400
    # Ragi-style milk + white compound (standard Ragi 25g each; Premium Ragi 40g each)
    ragi_milk_white_compound_g = 25
    if 'premium ragi' in variety_lower:
        white_sugar_g = 0
        brown_sugar_g = 104  # 52g white sugar replaced by brown + 52g brown (same as Ragi total sugar)
        ragi_milk_white_compound_g = 40
    
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
    if white_sugar_g > 0 and white_sugar:
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
    
    # Milk compound and white compound (Ragi Brownie and Premium Ragi Brownie)
    if 'ragi' in variety_lower:
        milk_compound = get_ingredient_price('Milk Compound')
        if milk_compound:
            price_per_g = milk_compound.get_price_per_gram()
            if price_per_g:
                mw = ragi_milk_white_compound_g
                cost = mw * price_per_g
                breakdown['ingredients'].append({
                    'name': 'Milk Compound',
                    'quantity': f'{mw}g',
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
                mw = ragi_milk_white_compound_g
                cost = mw * price_per_g
                breakdown['ingredients'].append({
                    'name': 'White Compound',
                    'quantity': f'{mw}g',
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


def _uses_three_regular_to_seven_small_cut(variety_name):
    """Classic / Ragi / Premium Ragi sold under ₹15 = small cut: 3 regular brownies → 7 pieces."""
    if not variety_name or not str(variety_name).strip():
        return False
    key = str(variety_name).strip().lower()
    return key in (
        'classic brownie',
        'ragi brownie',
        'premium ragi brownie',
    )


def calculate_brownies_from_price(price, variety_name=None):
    """
    Brownie-equivalents per ordered unit (for cost and production tallies).

    Rules:
    1. If price < 15:
       - Classic Brownie, Ragi Brownie, Premium Ragi Brownie: 3/7 (three regulars cut into seven smalls)
       - Else: 0.5 brownie
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
    
    if price_float < 15:
        if _uses_three_regular_to_seven_small_cut(variety_name):
            return 3.0 / 7.0
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


def _effective_order_quantity(order):
    """Units billed after returns (used for revenue/pricing)."""
    return max(0, (order.quantity or 0) - (order.returns or 0))


def _produced_order_quantity(order):
    """Units actually produced, including returns.

    Returned items still cost money to make, so cost/profit calculations use the
    full produced quantity even though revenue is based on the effective quantity."""
    return max(0, (order.quantity or 0))


def _order_courier_float(order):
    """Parcel / courier charge (₹) on the order."""
    if getattr(order, 'is_sample', False):
        return 0.0
    return float(order.courier_price) if order.courier_price else 0.0


def order_goods_revenue(order):
    """Product line revenue: unit price × effective quantity (after returns).

    Sample orders are given away for free, so they earn ₹0 revenue (their cost is
    still counted elsewhere via the recipe/price-derived calculation)."""
    if getattr(order, 'is_sample', False):
        return 0.0
    return float(order.price) * _effective_order_quantity(order)


def order_total_receivable(order):
    """Amount the customer owes for the order: goods + parcel/courier."""
    if getattr(order, 'is_sample', False):
        return 0.0
    return order_goods_revenue(order) + _order_courier_float(order)


def calculate_total_cost_and_profit(orders):
    """Calculate total ingredient cost and profit for a list of orders.

    Cost rule:
      - total_cost uses the PRODUCED quantity (includes returned items) so the
        full manufacturing expense is visible in reports.
    Profit rule:
      - profit uses the EFFECTIVE quantity (after returns) for cost, so returned
        items do NOT reduce the profit figure — they are a separate write-off.
    """
    if IngredientPrice is None:
        # Fallback to 30% margin if ingredient prices not available
        gross = sum(order_total_receivable(o) for o in orders)
        return gross * 0.30, gross * 0.30

    total_cost = 0
    profit_cost = 0   # cost of effectively sold items only (for profit calc)
    goods_revenue = 0

    for order in orders:
        variety = order.variety
        variety_name = variety.name if variety else 'Classic Brownie'

        effective_quantity = _effective_order_quantity(order)
        produced_quantity = _produced_order_quantity(order)

        breakdown = get_cost_breakdown(variety_name)
        cost_per_brownie = breakdown.get('cost_per_brownie') if breakdown else None

        if cost_per_brownie is None:
            continue

        if (variety and variety.is_combo_pack()) or is_cookie(variety_name):
            total_cost  += cost_per_brownie * produced_quantity
            profit_cost += cost_per_brownie * effective_quantity
            goods_revenue += order_goods_revenue(order)
        else:
            order_price = float(order.price)
            brownies_per_unit = calculate_brownies_from_price(order_price, variety_name)
            total_cost  += brownies_per_unit * float(produced_quantity)  * cost_per_brownie
            profit_cost += brownies_per_unit * float(effective_quantity) * cost_per_brownie
            goods_revenue += order_goods_revenue(order)

    total_courier = sum(_order_courier_float(o) for o in orders)
    profit = goods_revenue - profit_cost - total_courier
    return profit, total_cost


def aggregate_variety_cost_breakdown_from_orders(orders):
    """Per-variety sales, ingredient cost, effective quantity, and brownie-equivalent count."""
    variety_cost_breakdown = {}
    for order in orders:
        variety = order.variety
        variety_name = variety.name if variety else 'Unknown'

        if variety_name not in variety_cost_breakdown:
            variety_cost_breakdown[variety_name] = {
                'sales': 0,
                'courier': 0,
                'cost': 0,          # full produced-qty cost (includes returns)
                'effective_cost': 0, # cost of sold items only (for profit calc)
                'quantity': 0,
                'brownies_count': 0,
            }

        breakdown = get_cost_breakdown(variety_name)
        cost_per_brownie = breakdown.get('cost_per_brownie') if breakdown else None

        if cost_per_brownie is None:
            continue

        effective_quantity = _effective_order_quantity(order)
        order_quantity = float(effective_quantity)
        # Full produced quantity used for cost display; effective qty for sales/units.
        produced_quantity = _produced_order_quantity(order)

        if variety and variety.is_combo_pack():
            order_cost = cost_per_brownie * produced_quantity
            effective_order_cost = cost_per_brownie * effective_quantity
            g_rev = order_goods_revenue(order)
            brownies_per_combo = get_brownies_in_combo_pack(variety)
            brownies_count = brownies_per_combo * effective_quantity
        elif is_cookie(variety_name):
            order_cost = cost_per_brownie * produced_quantity
            effective_order_cost = cost_per_brownie * effective_quantity
            g_rev = order_goods_revenue(order)
            brownies_count = effective_quantity
        else:
            order_price = float(order.price)
            brownies_per_unit = calculate_brownies_from_price(order_price, variety_name)
            brownies_count = brownies_per_unit * order_quantity
            order_cost = brownies_per_unit * float(produced_quantity) * cost_per_brownie
            effective_order_cost = brownies_per_unit * float(effective_quantity) * cost_per_brownie
            g_rev = order_goods_revenue(order)

        variety_cost_breakdown[variety_name]['sales'] += g_rev
        variety_cost_breakdown[variety_name]['courier'] += _order_courier_float(order)
        variety_cost_breakdown[variety_name]['cost'] += order_cost
        variety_cost_breakdown[variety_name]['effective_cost'] += effective_order_cost
        variety_cost_breakdown[variety_name]['quantity'] += order_quantity
        variety_cost_breakdown[variety_name]['brownies_count'] += brownies_count

    return variety_cost_breakdown


def format_variety_breakdown_rows(variety_cost_breakdown):
    """Sorted rows for reports; goods sales + courier in totals; profit nets parcel cost."""
    variety_breakdown = []
    for variety_name, data in variety_cost_breakdown.items():
        g_sales = data['sales']
        courier = float(data.get('courier') or 0)
        revenue = g_sales + courier
        profit = g_sales - data.get('effective_cost', data['cost']) - courier
        profit_pct = (profit / revenue * 100) if revenue > 0 else 0
        variety_obj = Variety.query.filter_by(name=variety_name).first()
        if (variety_obj and variety_obj.is_combo_pack()) or is_cookie(variety_name):
            cost_per_unit = round(data['cost'] / data['quantity'], 2) if data['quantity'] > 0 else 0
        else:
            cost_per_unit = round(data['cost'] / data['brownies_count'], 2) if data['brownies_count'] > 0 else 0
        avg_sale_price = round(g_sales / data['quantity'], 2) if data['quantity'] > 0 else 0
        variety_breakdown.append({
            'name': variety_name,
            'sales': round(revenue, 2),
            'cost': round(data['cost'], 2),
            'profit': round(profit, 2),
            'profit_percentage': round(profit_pct, 2),
            'quantity': data['quantity'],
            'brownies_count': round(data['brownies_count'], 2),
            'cost_per_brownie': cost_per_unit,
            'avg_sale_price': avg_sale_price,
        })
    variety_breakdown.sort(key=lambda x: x['sales'], reverse=True)
    return variety_breakdown


@app.route('/')
def index():
    """Dashboard with quick order entry form"""
    varieties = Variety.query.order_by(Variety.name).all()
    shops = Shop.query.order_by(Shop.name).all()
    variety_list_prices = variety_list_prices_map(varieties)

    # Build a JSON-safe list of templates for the "apply from template" UI
    variety_name_by_id = {v.id: v.name for v in varieties}
    templates_for_ui = []
    if USE_GOOGLE_SHEETS:
        try:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            for t in gs.get_templates():
                items = []
                for item in t.get('items', []):
                    try:
                        vid = int(item.get('id') if 'id' in item else item.get('variety_id'))
                    except (ValueError, TypeError):
                        continue
                    qty = int(item.get('quantity', 1) or 1)
                    amount = float(item.get('amount', 0) or 0)
                    items.append({
                        'variety_name': variety_name_by_id.get(vid, f'Variety #{vid}'),
                        'quantity': qty,
                        'amount': amount,
                    })
                templates_for_ui.append({
                    'id': t['id'],
                    'shop_id': t.get('shop_id'),
                    'name': t.get('name', ''),
                    'items': items,
                })
        except Exception:
            pass  # Templates unavailable – page still works without them

    return render_template(
        'index.html',
        varieties=varieties,
        shops=shops,
        variety_list_prices=variety_list_prices,
        templates_for_ui=templates_for_ui,
    )


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
        is_sample = request.form.get('is_sample', type=str) == 'true'
        
        # Validation
        if not variety_id or not shop_id or not quantity or price is None or not delivery_date_str:
            flash('All fields are required', 'error')
            return redirect(url_for('index'))
        
        if quantity <= 0 or price < 0:
            flash('Quantity must be positive; price must be 0 or more', 'error')
            return redirect(url_for('index'))
        
        if returns < 0 or returns > quantity:
            flash('Returns must be between 0 and quantity', 'error')
            return redirect(url_for('index'))
        
        # Calculate effective quantity (quantity - returns)
        effective_quantity = max(0, quantity - returns)
        
        if is_sample:
            # Sample order: keep the (cost-basis) price so cost is counted, but it is
            # given away for free, so it is fully "paid" at ₹0 and never pending.
            payment_status = 'paid'
            paid_amount = 0
            courier_price = 0
            total_amount = 0.0
        else:
            # Validate payment status
            if payment_status not in ['paid', 'unpaid', 'partial']:
                payment_status = 'unpaid'
            
            goods_amt = float(price) * effective_quantity
            total_amount = goods_amt + float(courier_price or 0)
            if payment_status == 'paid':
                paid_amount = total_amount
            elif payment_status == 'partial':
                if paid_amount <= 0 or paid_amount >= total_amount:
                    flash('Partial payment amount must be greater than 0 and less than total order amount (including courier)', 'error')
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
                returns,
                is_sample
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
                courier_price=Decimal(str(courier_price)),
                is_sample=is_sample
            )
            db_session.add(order)
            db_session.commit()
            order_total = order_total_receivable(order)
        
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
    variety_list_prices = variety_list_prices_map(varieties_list)
    return render_template(
        'varieties.html',
        varieties=varieties_list,
        all_varieties=all_varieties,
        variety_list_prices=variety_list_prices,
    )


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
        
        # Set combo_pack_config to empty string if no items, or JSON object with items
        if combo_items:
            combo_pack_config = json.dumps({
                "items": combo_items,
                "extra_packing_cost": 5.0
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
        
        # Preserve existing packing cost from config, or default to 5.0
        existing_packing_cost = variety.get_extra_packing_cost() if combo_items else 5.0

        # Set combo_pack_config to empty string if no items, or JSON object with items
        if combo_items:
            combo_pack_config = json.dumps({
                "items": combo_items,
                "extra_packing_cost": existing_packing_cost
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


@app.route('/templates')
def order_templates():
    """List and manage per-shop order templates."""
    shops_list = Shop.query.order_by(Shop.name).all()
    varieties_list = Variety.query.order_by(Variety.name).all()
    variety_list_prices = variety_list_prices_map(varieties_list)

    shop_name_by_id = {s.id: s.name for s in shops_list}
    variety_name_by_id = {v.id: v.name for v in varieties_list}

    templates_raw = []
    if USE_GOOGLE_SHEETS:
        from google_sheets import get_gs_db
        gs = get_gs_db()
        templates_raw = gs.get_templates()

    # Enrich templates with display names and computed totals
    templates = []
    for t in templates_raw:
        items = []
        total = 0.0
        for item in t.get('items', []):
            try:
                vid = int(item.get('id') if 'id' in item else item.get('variety_id'))
            except (ValueError, TypeError):
                continue
            qty = int(item.get('quantity', 1) or 1)
            amount = float(item.get('amount', 0) or 0)
            total += amount * qty
            items.append({
                'variety_id': vid,
                'variety_name': variety_name_by_id.get(vid, f'Variety #{vid}'),
                'quantity': qty,
                'amount': amount,
            })
        templates.append({
            'id': t['id'],
            'shop_id': t.get('shop_id'),
            'shop_name': shop_name_by_id.get(t.get('shop_id'), 'Unknown shop'),
            'name': t.get('name'),
            'items': items,
            'total': round(total, 2),
        })

    templates.sort(key=lambda x: (x['shop_name'] or '', x['name'] or ''))

    return render_template(
        'templates.html',
        templates=templates,
        shops=shops_list,
        varieties=varieties_list,
        variety_list_prices=variety_list_prices,
        today_iso=date.today().isoformat(),
        sheets_enabled=USE_GOOGLE_SHEETS,
    )


@app.route('/templates/add', methods=['POST'])
def add_template():
    """Create a new per-shop template with one or more variety lines."""
    if not USE_GOOGLE_SHEETS:
        flash('Templates are only available when using Google Sheets.', 'error')
        return redirect(url_for('order_templates'))
    try:
        shop_id = request.form.get('shop_id', type=int)
        name = (request.form.get('name') or '').strip()
        variety_ids = request.form.getlist('variety_id')
        quantities = request.form.getlist('quantity')
        amounts = request.form.getlist('amount')

        if not shop_id or not name:
            flash('Shop and template name are required.', 'error')
            return redirect(url_for('order_templates'))

        items = []
        for idx, vid in enumerate(variety_ids):
            if not vid:
                continue
            try:
                variety_id = int(vid)
            except (ValueError, TypeError):
                continue
            try:
                qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1
            except (ValueError, TypeError):
                qty = 1
            try:
                amount = float(amounts[idx]) if idx < len(amounts) and amounts[idx] else 0.0
            except (ValueError, TypeError):
                amount = 0.0
            if qty <= 0:
                continue
            items.append({'id': variety_id, 'quantity': qty, 'amount': amount})

        if not items:
            flash('Add at least one variety line to the template.', 'error')
            return redirect(url_for('order_templates'))

        from google_sheets import get_gs_db
        gs = get_gs_db()
        gs.add_template(shop_id, name, items)

        flash(f'Template "{name}" created successfully.', 'success')
        return redirect(url_for('order_templates'))

    except Exception as e:
        flash(f'Error creating template: {str(e)}', 'error')
        return redirect(url_for('order_templates'))


@app.route('/templates/delete/<int:id>', methods=['POST'])
def delete_template(id):
    """Delete a template."""
    if not USE_GOOGLE_SHEETS:
        flash('Templates are only available when using Google Sheets.', 'error')
        return redirect(url_for('order_templates'))
    try:
        from google_sheets import get_gs_db
        gs = get_gs_db()
        gs.delete_template(id)
        flash('Template deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting template: {str(e)}', 'error')
    return redirect(url_for('order_templates'))


@app.route('/templates/<int:id>/apply', methods=['POST'])
def apply_template(id):
    """Apply a template: create one order per variety line at once."""
    if not USE_GOOGLE_SHEETS:
        flash('Templates are only available when using Google Sheets.', 'error')
        return redirect(url_for('order_templates'))
    try:
        from google_sheets import get_gs_db
        gs = get_gs_db()

        template = next((t for t in gs.get_templates() if t['id'] == id), None)
        if not template:
            flash('Template not found.', 'error')
            return redirect(url_for('order_templates'))

        delivery_date_str = request.form.get('delivery_date')
        payment_status = request.form.get('payment_status', 'unpaid')
        if payment_status not in ['paid', 'unpaid']:
            payment_status = 'unpaid'

        try:
            delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Choose a valid delivery date.', 'error')
            return redirect(url_for('order_templates'))

        shop_id = template.get('shop_id')
        created = 0
        for item in template.get('items', []):
            try:
                variety_id = int(item.get('id') if 'id' in item else item.get('variety_id'))
            except (ValueError, TypeError):
                continue
            qty = int(item.get('quantity', 1) or 1)
            amount = float(item.get('amount', 0) or 0)
            if qty <= 0 or amount <= 0:
                continue

            line_total = amount * qty
            paid_amount = line_total if payment_status == 'paid' else 0

            gs.add_order(
                variety_id,
                shop_id,
                qty,
                Decimal(str(amount)),
                delivery_date,
                payment_status,
                Decimal(str(paid_amount)),
                Decimal('0'),
                0,
                False
            )
            created += 1

        if created == 0:
            flash('Template has no valid lines to create orders from.', 'error')
            return redirect(url_for('order_templates'))

        flash(f'Created {created} order(s) from template "{template.get("name")}".', 'success')
        return redirect(url_for('orders', shop_id=shop_id))

    except Exception as e:
        flash(f'Error applying template: {str(e)}', 'error')
        return redirect(url_for('order_templates'))


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
            order_total = order_total_receivable(order)
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
            order_total = order_total_receivable(order)
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
        order_total = order_total_receivable(order)
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


def _available_years_from_orders():
    current_year = datetime.now().year
    if USE_GOOGLE_SHEETS:
        all_orders = Order.query.all()
        years = sorted(
            set(order.delivery_date.year for order in all_orders if order.delivery_date),
            reverse=True,
        )
    else:
        years = db.session.query(extract('year', Order.delivery_date).label('year')).distinct().order_by(text('year desc')).all()
        years = [int(y[0]) for y in years if y[0]]
    return years if years else [current_year]


def _compute_monthly_production_breakdown(
    selected_year,
    selected_month,
    egg_price_per_piece,
    sugar_price_per_kg,
    brown_sugar_price_per_kg,
    maida_price_per_kg,
):
    """Egg/sugar/maida production cost for orders in a calendar month."""
    if USE_GOOGLE_SHEETS:
        all_orders = Order.query.all()
        orders = [
            order
            for order in all_orders
            if order.delivery_date
            and order.delivery_date.year == selected_year
            and order.delivery_date.month == selected_month
        ]
    else:
        orders = Order.query.filter(
            extract('year', Order.delivery_date) == selected_year,
            extract('month', Order.delivery_date) == selected_month,
        ).all()

    total_brownies = 0
    for order in orders:
        variety = order.variety
        variety_name = variety.name if variety else None
        order_quantity = float(_effective_order_quantity(order))

        if variety and variety.is_combo_pack():
            brownies_per_combo = get_brownies_in_combo_pack(variety)
            brownies_for_order = brownies_per_combo * order_quantity
        else:
            order_price = float(order.price)
            brownies_per_unit = calculate_brownies_from_price(order_price, variety_name)
            brownies_for_order = brownies_per_unit * order_quantity

        total_brownies += brownies_for_order

    batches_of_4 = total_brownies / 4.0
    total_eggs_needed = batches_of_4
    total_sugar_needed_kg = (batches_of_4 * 13) / 1000.0
    total_brown_sugar_needed_kg = (batches_of_4 * 13) / 1000.0
    total_maida_needed_kg = (batches_of_4 * 30) / 1000.0

    egg_cost = total_eggs_needed * egg_price_per_piece
    sugar_cost = total_sugar_needed_kg * sugar_price_per_kg
    brown_sugar_cost = total_brown_sugar_needed_kg * brown_sugar_price_per_kg
    maida_cost = total_maida_needed_kg * maida_price_per_kg
    total_cost = egg_cost + sugar_cost + brown_sugar_cost + maida_cost

    return {
        'selected_year': selected_year,
        'selected_month': selected_month,
        'month_name': datetime(selected_year, selected_month, 1).strftime('%B %Y'),
        'total_brownies': total_brownies,
        'total_orders': len(orders),
        'egg': {
            'quantity': total_eggs_needed,
            'unit': 'pieces',
            'price_per_unit': egg_price_per_piece,
            'total_cost': egg_cost,
        },
        'sugar': {
            'quantity': total_sugar_needed_kg,
            'unit': 'kg',
            'price_per_unit': sugar_price_per_kg,
            'total_cost': sugar_cost,
        },
        'brown_sugar': {
            'quantity': total_brown_sugar_needed_kg,
            'unit': 'kg',
            'price_per_unit': brown_sugar_price_per_kg,
            'total_cost': brown_sugar_cost,
        },
        'maida': {
            'quantity': total_maida_needed_kg,
            'unit': 'kg',
            'price_per_unit': maida_price_per_kg,
            'total_cost': maida_cost,
        },
        'total_cost': total_cost,
    }


def _ingredients_page_data(
    breakdown=None,
    selected_year=None,
    selected_month=None,
    egg_price=None,
    sugar_price=None,
    brown_sugar_price=None,
    maida_price=None,
):
    current_month = datetime.now().month
    current_year = datetime.now().year
    available_years = _available_years_from_orders()

    ingredients_list = IngredientPrice.query.order_by(IngredientPrice.name).all()
    varieties = Variety.query.order_by(Variety.name).all()
    variety_breakdowns = {}
    variety_info = {}
    variety_id_to_name = {}

    for variety in varieties:
        variety_id_to_name[variety.id] = variety.name
        vb = get_cost_breakdown(variety.name)
        if vb:
            variety_breakdowns[variety.name] = vb
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
                'combo_pack_items_display': combo_items_display,
            }

    return {
        'ingredients': ingredients_list,
        'variety_breakdowns': variety_breakdowns,
        'variety_info': variety_info,
        'available_years': available_years,
        'current_month': current_month,
        'current_year': current_year,
        'selected_year': selected_year if selected_year is not None else current_year,
        'selected_month': selected_month if selected_month is not None else current_month,
        'egg_price': egg_price,
        'sugar_price': sugar_price,
        'brown_sugar_price': brown_sugar_price,
        'maida_price': maida_price,
        'breakdown': breakdown,
    }


def _handle_production_cost_post():
    current_month = datetime.now().month
    current_year = datetime.now().year
    try:
        selected_year = request.form.get('year', type=int, default=current_year)
        selected_month = request.form.get('month', type=int, default=current_month)
        egg_price_per_piece = request.form.get('egg_price', type=float, default=0)
        sugar_price_per_kg = request.form.get('sugar_price', type=float, default=0)
        brown_sugar_price_per_kg = request.form.get('brown_sugar_price', type=float, default=0)
        maida_price_per_kg = request.form.get('maida_price', type=float, default=0)

        breakdown = _compute_monthly_production_breakdown(
            selected_year,
            selected_month,
            egg_price_per_piece,
            sugar_price_per_kg,
            brown_sugar_price_per_kg,
            maida_price_per_kg,
        )
        return render_template(
            'ingredients.html',
            **_ingredients_page_data(
                breakdown=breakdown,
                selected_year=selected_year,
                selected_month=selected_month,
                egg_price=egg_price_per_piece,
                sugar_price=sugar_price_per_kg,
                brown_sugar_price=brown_sugar_price_per_kg,
                maida_price=maida_price_per_kg,
            ),
        )
    except Exception as e:
        flash(f'Error calculating costs: {str(e)}', 'error')
        return render_template(
            'ingredients.html',
            **_ingredients_page_data(
                breakdown=None,
                selected_year=request.form.get('year', type=int, default=current_year),
                selected_month=request.form.get('month', type=int, default=current_month),
                egg_price=request.form.get('egg_price', type=float),
                sugar_price=request.form.get('sugar_price', type=float),
                brown_sugar_price=request.form.get('brown_sugar_price', type=float),
                maida_price=request.form.get('maida_price', type=float),
            ),
        )


@app.route('/ingredients', methods=['GET', 'POST'])
def ingredients():
    """Ingredients cost management page"""
    if request.method == 'POST' and request.form.get('production_cost_calc'):
        return _handle_production_cost_post()

    if request.method == 'POST':
        try:
            ingredients_list = IngredientPrice.query.all()
            for ingredient in ingredients_list:
                price_key = f'price_{ingredient.id}'
                new_price = request.form.get(price_key, type=float)
                if new_price is not None and new_price >= 0:
                    if USE_GOOGLE_SHEETS:
                        from google_sheets import get_gs_db
                        gs = get_gs_db()
                        gs.update_ingredient_price(
                            ingredient.id,
                            ingredient.name,
                            Decimal(str(new_price)),
                            ingredient.unit,
                            ingredient.package_size,
                            ingredient.package_unit,
                        )
                    else:
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

    return render_template('ingredients.html', **_ingredients_page_data())


@app.route('/cost-breakdown', methods=['GET', 'POST'])
def cost_breakdown():
    """Legacy URL: production cost calculator lives on the Ingredients page."""
    if request.method == 'GET':
        return redirect(url_for('ingredients') + '#production-cost')
    return _handle_production_cost_post()


@app.route('/reports')
def reports():
    """Sales & profit dashboard (date range, shop filter, charts, variety cost table)."""
    shops = Shop.query.order_by(Shop.name).all()
    today_iso = date.today().isoformat()
    return render_template('reports.html', shops=shops, today_iso=today_iso)


def _order_delivery_date(order):
    if not order.delivery_date:
        return None
    d = order.delivery_date
    return d.date() if hasattr(d, 'date') else d


def _parse_dashboard_iso_date(s):
    if not s or not str(s).strip():
        return None
    return datetime.strptime(str(s).strip(), '%Y-%m-%d').date()


def _resolve_report_date_range(preset, date_from_str, date_to_str):
    """Inclusive (start_date, end_date). preset: this_month, last_month, this_year, last_year, custom."""
    today = date.today()
    preset = (preset or 'this_month').strip().lower()

    if preset == 'custom':
        start = _parse_dashboard_iso_date(date_from_str)
        end = _parse_dashboard_iso_date(date_to_str)
        if not start or not end:
            raise ValueError('Choose both start and end dates for a custom range.')
        if start > end:
            start, end = end, start
        return start, end

    if preset == 'this_month':
        y, m = today.year, today.month
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        return start, end

    if preset == 'last_month':
        if today.month == 1:
            y, m = today.year - 1, 12
        else:
            y, m = today.year, today.month - 1
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        return start, end

    if preset == 'all_time':
        return date(2000, 1, 1), today

    if preset == 'this_year':
        return date(today.year, 1, 1), date(today.year, 12, 31)

    if preset == 'last_year':
        y = today.year - 1
        return date(y, 1, 1), date(y, 12, 31)

    y, m = today.year, today.month
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start, end


def _filter_orders_by_range_and_shop(all_orders, start_d, end_d, shop_id):
    out = []
    for o in all_orders:
        od = _order_delivery_date(o)
        if od is None or od < start_d or od > end_d:
            continue
        if shop_id and getattr(o, 'shop_id', None) != shop_id:
            continue
        out.append(o)
    return out


def _build_sales_profit_trends(orders, start_d, end_d, trend_mode='auto'):
    """Time buckets in [start_d, end_d], capped at today. trend_mode: auto|daily|weekly|monthly|yearly."""
    trend_mode = (trend_mode or 'auto').strip().lower()
    if trend_mode not in ('auto', 'daily', 'weekly', 'monthly', 'yearly'):
        trend_mode = 'auto'

    today = date.today()
    trend_end = min(end_d, today)
    span_days = (end_d - start_d).days + 1

    if trend_mode == 'auto':
        if span_days <= 45:
            granularity = 'daily'
        elif span_days <= 240:
            granularity = 'weekly'
        else:
            granularity = 'monthly'
    else:
        granularity = trend_mode

    if trend_end < start_d:
        return {'labels': [], 'sales': [], 'profit': [], 'granularity': granularity}

    by_bucket = defaultdict(list)
    for o in orders:
        od = _order_delivery_date(o)
        if od is None or od < start_d or od > trend_end:
            continue
        if granularity == 'daily':
            by_bucket[od].append(o)
        elif granularity == 'weekly':
            y, w, _ = od.isocalendar()
            by_bucket[(y, w)].append(o)
        elif granularity == 'monthly':
            by_bucket[(od.year, od.month)].append(o)
        else:
            by_bucket[od.year].append(o)

    if granularity == 'daily':
        keys = []
        d = start_d
        while d <= trend_end:
            keys.append(d)
            d += timedelta(days=1)
        labels = [k.strftime('%d %b') for k in keys]
    elif granularity == 'weekly':
        keys_set = set()
        cur = start_d
        while cur <= trend_end:
            y, w, _ = cur.isocalendar()
            keys_set.add((y, w))
            cur += timedelta(days=1)
        keys = sorted(keys_set, key=lambda x: (x[0], x[1]))
        labels = [f'W{k[1]} {k[0]}' for k in keys]
    elif granularity == 'monthly':
        keys = []
        end_cap = (trend_end.year, trend_end.month)
        y, m = start_d.year, start_d.month
        while (y, m) <= end_cap:
            keys.append((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        labels = [datetime(y, m, 1).strftime('%b %Y') for y, m in keys]
    else:
        keys = list(range(start_d.year, trend_end.year + 1))
        labels = [str(y) for y in keys]

    sales_vals = []
    profit_vals = []
    for k in keys:
        bl = by_bucket.get(k, [])
        ts = sum(order_total_receivable(o) for o in bl)
        margin, _tc = calculate_total_cost_and_profit(bl)
        sales_vals.append(round(ts, 2))
        profit_vals.append(round(margin, 2))

    return {
        'labels': labels,
        'sales': sales_vals,
        'profit': profit_vals,
        'granularity': granularity,
    }


def _build_report_dict_from_orders(orders):
    """Aggregate report payload: revenue = goods (after returns) + parcel/courier per order."""
    total_sales = sum(order_total_receivable(o) for o in orders)
    total_paid = sum(float(order.paid_amount) if order.paid_amount else 0 for order in orders)
    total_pending = total_sales - total_paid
    margin, total_cost = calculate_total_cost_and_profit(orders)
    profit_percentage = (margin / total_sales * 100) if total_sales > 0 else 0

    shop_dict = {}
    for order in orders:
        shop = order.shop
        shop_name = shop.name if shop else 'Unknown'
        if shop_name not in shop_dict:
            shop_dict[shop_name] = {'total': 0, 'paid': 0}
        shop_dict[shop_name]['total'] += order_total_receivable(order)
        shop_dict[shop_name]['paid'] += float(order.paid_amount) if order.paid_amount else 0

    shop_totals = sorted(
        [(name, data['total'], data['paid']) for name, data in shop_dict.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    shop_data = {
        'labels': [s[0] for s in shop_totals],
        'values': [float(s[1]) for s in shop_totals],
        'pending': [float(s[1]) - float(s[2]) for s in shop_totals],
    }

    variety_dict = {}
    for order in orders:
        variety = order.variety
        variety_name = variety.name if variety else 'Unknown'
        if variety_name not in variety_dict:
            variety_dict[variety_name] = 0
        variety_dict[variety_name] += order_total_receivable(order)

    variety_totals = sorted(variety_dict.items(), key=lambda x: x[1], reverse=True)
    variety_data = {
        'labels': [v[0] for v in variety_totals],
        'values': [float(v[1]) for v in variety_totals],
    }

    variety_cost_breakdown = aggregate_variety_cost_breakdown_from_orders(orders)
    variety_breakdown = format_variety_breakdown_rows(variety_cost_breakdown)

    total_orders = len(orders)
    avg_order_value = total_sales / total_orders if total_orders > 0 else 0

    return {
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
        'avg_order_value': round(avg_order_value, 2),
    }


@app.route('/api/reports/dashboard')
def api_reports_dashboard():
    """Single endpoint: presets or custom dates, optional shop; pies, summary, variety table, trends."""
    try:
        preset = request.args.get('preset', 'this_month')
        date_from = request.args.get('from')
        date_to = request.args.get('to')
        shop_id = request.args.get('shop_id', type=int)
        trend_bucket = request.args.get('trend_bucket', 'auto')

        start_d, end_d = _resolve_report_date_range(preset, date_from, date_to)
        all_orders = Order.query.all()

        # For "all time", clamp the start to the earliest order so trend buckets and the
        # period label reflect real data instead of spanning back to year 2000.
        if (preset or '').strip().lower() == 'all_time':
            order_dates = [d for d in (_order_delivery_date(o) for o in all_orders) if d is not None]
            if order_dates:
                start_d = min(order_dates)

        orders = _filter_orders_by_range_and_shop(all_orders, start_d, end_d, shop_id)

        payload = _build_report_dict_from_orders(orders)
        trends = _build_sales_profit_trends(orders, start_d, end_d, trend_bucket)
        payload['period'] = {
            'start': start_d.isoformat(),
            'end': end_d.isoformat(),
            'label': f"{start_d.strftime('%d %b %Y')} – {end_d.strftime('%d %b %Y')}",
            'preset': preset,
        }
        payload['trend_labels'] = trends['labels']
        payload['trend_sales'] = trends['sales']
        payload['trend_profit'] = trends['profit']
        payload['trend_granularity'] = trends['granularity']
        payload['trend_bucket_request'] = (trend_bucket or 'auto').strip().lower()
        return jsonify(payload)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/overall')
def api_overall_report():
    """JSON API endpoint for overall/all-time report data"""
    try:
        orders = Order.query.all()
        return jsonify(_build_report_dict_from_orders(orders))
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

            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    'label': month_label,
                    'orders': [],
                    'sales': 0,
                    'cost': 0
                }
            
            monthly_data[month_key]['orders'].append(order)
            monthly_data[month_key]['sales'] += order_total_receivable(order)
        
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
        if USE_GOOGLE_SHEETS:
            all_orders = Order.query.all()
            orders = [
                order
                for order in all_orders
                if order.delivery_date
                and order.delivery_date.year == year
                and order.delivery_date.month == month
            ]
        else:
            orders = Order.query.filter(
                extract('year', Order.delivery_date) == year,
                extract('month', Order.delivery_date) == month,
            ).all()

        return jsonify(_build_report_dict_from_orders(orders))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/yearly/<int:year>')
def api_yearly_report(year):
    """JSON API: all orders in the given calendar year."""
    try:
        if USE_GOOGLE_SHEETS:
            all_orders = Order.query.all()
            orders = [
                order
                for order in all_orders
                if order.delivery_date and order.delivery_date.year == year
            ]
        else:
            orders = Order.query.filter(extract('year', Order.delivery_date) == year).all()

        return jsonify(_build_report_dict_from_orders(orders))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/monthly-trend')
def api_monthly_trend():
    """Monthly sales + profit for one year; optional shop_id filter."""
    try:
        year = request.args.get('year', type=int) or datetime.now().year
        shop_id = request.args.get('shop_id', type=int)

        all_orders = Order.query.all()
        filtered = []
        for order in all_orders:
            if not order.delivery_date:
                continue
            if order.delivery_date.year != year:
                continue
            if shop_id and order.shop_id != shop_id:
                continue
            filtered.append(order)

        buckets = {m: [] for m in range(1, 13)}
        for order in filtered:
            buckets[order.delivery_date.month].append(order)

        labels = []
        sales_series = []
        profit_series = []
        for m in range(1, 13):
            labels.append(datetime(year, m, 1).strftime('%b %Y'))
            month_orders = buckets[m]
            ts = sum(order_total_receivable(o) for o in month_orders)
            margin, _tc = calculate_total_cost_and_profit(month_orders)
            sales_series.append(round(ts, 2))
            profit_series.append(round(margin, 2))

        return jsonify({
            'year': year,
            'shop_id': shop_id,
            'labels': labels,
            'sales': sales_series,
            'profit': profit_series,
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
        order_total = order_total_receivable(order)
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
        order_total = order_total_receivable(order)
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
            is_sample = request.form.get('is_sample', type=str) == 'true'
            
            # Validation
            if not variety_id or not shop_id or not quantity or price is None or not delivery_date_str:
                flash('All fields are required', 'error')
                return redirect(url_for('edit_order', id=id))
            
            if quantity <= 0 or price < 0:
                flash('Quantity must be positive; price must be 0 or more', 'error')
                return redirect(url_for('edit_order', id=id))
            
            if returns < 0 or returns > quantity:
                flash('Returns must be between 0 and quantity', 'error')
                return redirect(url_for('edit_order', id=id))
            
            # Calculate effective quantity (quantity - returns)
            effective_quantity = max(0, quantity - returns)
            
            if is_sample:
                # Sample order: counted in cost but sold at ₹0
                payment_status = 'paid'
                paid_amount = 0.00
                courier_price = 0.00
            
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
                    returns,
                    is_sample
                )
                total = 0.0 if is_sample else float(Decimal(str(price)) * effective_quantity) + float(courier_price or 0)
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
                order.is_sample = is_sample
                db_session.commit()
                total = order_total_receivable(order)

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
        total_amount = order_total_receivable(order)

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
                order.returns or 0,
                bool(getattr(order, 'is_sample', False))
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
            order_total = order_total_receivable(order)
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
                order_total = order_total_receivable(order)
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
                    order.returns or 0,
                    bool(getattr(order, 'is_sample', False))
                )
        else:
            for order in unpaid_orders:
                order_total = order_total_receivable(order)
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


@app.route('/shops/<int:shop_id>/record-payment', methods=['POST'])
def record_shop_payment(shop_id):
    """Record a lump-sum payment from a shop and allocate it across that shop's
    outstanding (not fully paid, non-sample) orders, oldest first.

    Orders fully covered become 'paid'; a partially covered order becomes 'partial'."""
    try:
        shop = Shop.query.get_or_404(shop_id)
        amount = request.form.get('amount', type=float)

        if not amount or amount <= 0:
            flash('Enter a payment amount greater than 0.', 'error')
            return redirect(url_for('orders', shop_id=shop_id))

        # Outstanding orders for this shop, oldest first (delivery date, then created time)
        shop_orders = Order.query.filter_by(shop_id=shop_id).all()

        def _created_sort_key(o):
            return o.created_at if o.created_at else datetime.min

        outstanding = []
        for order in shop_orders:
            if getattr(order, 'is_sample', False):
                continue
            receivable = order_total_receivable(order)
            paid_amt = float(order.paid_amount) if order.paid_amount else 0
            if receivable - paid_amt > 0.001:
                outstanding.append(order)

        outstanding.sort(key=lambda o: (o.delivery_date, _created_sort_key(o)))

        if not outstanding:
            flash(f'All orders for {shop.name} are already paid!', 'info')
            return redirect(url_for('orders', shop_id=shop_id))

        remaining = float(amount)
        updated_count = 0
        applied_total = 0.0

        for order in outstanding:
            if remaining <= 0.001:
                break
            receivable = order_total_receivable(order)
            paid_amt = float(order.paid_amount) if order.paid_amount else 0
            pending = receivable - paid_amt
            if pending <= 0:
                continue

            pay_now = min(remaining, pending)
            new_paid = paid_amt + pay_now
            new_status = 'paid' if (receivable - new_paid) <= 0.001 else 'partial'
            if new_status == 'paid':
                new_paid = receivable

            if USE_GOOGLE_SHEETS:
                from google_sheets import get_gs_db
                gs = get_gs_db()
                gs.update_order(
                    order.id,
                    order.variety_id,
                    order.shop_id,
                    order.quantity,
                    order.price,
                    order.delivery_date,
                    new_status,
                    Decimal(str(new_paid)),
                    order.courier_price or 0,
                    order.returns or 0,
                    bool(getattr(order, 'is_sample', False))
                )
            else:
                order.payment_status = new_status
                order.paid_amount = Decimal(str(new_paid))

            remaining -= pay_now
            applied_total += pay_now
            updated_count += 1

        if not USE_GOOGLE_SHEETS:
            db_session.commit()

        msg = f'Recorded ₹{applied_total:.2f} across {updated_count} order(s) for {shop.name}.'
        if remaining > 0.001:
            msg += f' ₹{remaining:.2f} left over (all orders are now paid).'
        flash(msg, 'success')
        return redirect(url_for('orders', shop_id=shop_id))

    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error recording payment: {str(e)}', 'error')
        return redirect(url_for('orders', shop_id=shop_id))


@app.route('/orders/delete/<int:id>', methods=['POST'])
def delete_order(id):
    """Delete a single order"""
    try:
        order = Order.query.get_or_404(id)
        shop_id = request.form.get('shop_id', type=int)
        pending_only = request.form.get('pending_only') == 'true'

        if USE_GOOGLE_SHEETS:
            from google_sheets import get_gs_db
            gs = get_gs_db()
            gs.delete_order(id)
        else:
            db_session.delete(order)
            db_session.commit()

        flash('Order deleted successfully', 'success')
    except Exception as e:
        if not USE_GOOGLE_SHEETS:
            db_session.rollback()
        flash(f'Error deleting order: {str(e)}', 'error')

    params = {}
    if shop_id:
        params['shop_id'] = shop_id
    if pending_only:
        params['pending_only'] = 'true'
    return redirect(url_for('orders', **params))


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

