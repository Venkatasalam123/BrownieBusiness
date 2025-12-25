# Brownie Sales Tracker

A Flask-based web application for tracking brownie orders, inventory, and sales. Designed for mobile-first use with minimal clicks and dropdown-heavy UI.

## Features

1. **Quick Order Entry** - Add new orders with minimal clicks using dropdowns
2. **Inventory Management** - Add and manage brownie varieties with default prices
3. **Shop/Customer Management** - Add and manage shops and customers (wholesale and retail)
4. **Monthly Sales Reports** - View sales reports with:
   - Total sales and margin (30% calculation)
   - Shop-wise and variety-wise pie charts
   - Breakdown tables
   - Summary statistics

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python app.py
```

3. Open your browser and navigate to:
```
http://localhost:5000
```

## Usage

1. **Add Varieties**: Go to "Varieties" page and add brownie varieties with default prices
2. **Add Shops/Customers**: Go to "Shops" page and add shops and customers
3. **Add Orders**: Use the main page to quickly add orders with dropdown selections
4. **View Reports**: Go to "Reports" page to view monthly sales data and charts

## Database

The application uses SQLite database (`brownie_sales.db`) which will be created automatically on first run.

## Mobile-Friendly Design

- Large touch-friendly buttons (minimum 44x44px)
- Full-width dropdowns and inputs
- Responsive design for mobile phones
- Minimal scrolling required
- Fast page loads
