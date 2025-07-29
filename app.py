"""
Main application file for VuaChuyenHang Pro.

This app uses FastAPI together with Jinja2 templates to provide a
lightweight web interface for managing customers and money transfer orders.
It stores data in a simple SQLite database and offers CRUD
operations for both customers and orders. Customers can look up
orders using a tracking number via a dedicated tracking page.

Additionally, the application can export a 4×6 inch receipt as a PDF
for any order. The PDF is rendered on the fly using Pillow
(`PIL`) and contains the most important fields from the order.
"""

from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont


# Location of the SQLite database.  The file will be created on
# application startup if it doesn’t already exist.
DATABASE = "data.db"

# Determine the absolute directory of this file.  This allows
# referencing the templates and static directories regardless of the
# current working directory.  Without this, importing the module from
# another location would cause FastAPI to look for 'templates' and
# 'static' relative to the wrong directory.
BASE_DIR = Path(__file__).resolve().parent


def get_db() -> sqlite3.Connection:
    """Open a connection to the SQLite database with row factory enabled.

    Each call returns a new connection; callers are responsible for
    closing the connection when done.  Using row_factory allows
    accessing columns by name instead of index.
    """
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create database tables if they don’t exist.

    This function runs on startup to ensure that the required tables
    (customers and orders) are present.  If the tables already
    exist then the creation commands have no effect.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                driver_license TEXT,
                birth_date TEXT,
                address TEXT,
                phone TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_name TEXT,
                receiver_address TEXT,
                receiver_phone TEXT,
                exchange_rate REAL,
                amount REAL,
                fee REAL,
                total REAL,
                send_date TEXT,
                tracking_number TEXT,
                status TEXT,
                FOREIGN KEY(sender_id) REFERENCES customers(id)
            )
            """
        )
        conn.commit()


app = FastAPI(title="VuaChuyenHang Pro", description="Money transfer management system")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Serve static files such as custom CSS.  Bootstrap is loaded via CDN
# inside templates to keep dependencies minimal.
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def startup_event() -> None:
    """Initialize application directories and database on startup."""
    # Ensure directories exist
    # Ensure necessary directories exist relative to this file
    (BASE_DIR / "static" / "css").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "templates").mkdir(parents=True, exist_ok=True)
    # Initialize database
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """Render the home page with a short introduction."""
    return templates.TemplateResponse("home.html", {"request": request})


# -------------------- Customer Routes --------------------

@app.get("/customers", response_class=HTMLResponse)
def list_customers(request: Request) -> HTMLResponse:
    """Display all customers in a table."""
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    conn.close()
    return templates.TemplateResponse(
        "customers.html", {"request": request, "customers": customers}
    )


@app.get("/customers/new", response_class=HTMLResponse)
def new_customer(request: Request) -> HTMLResponse:
    """Show an empty form for creating a new customer."""
    return templates.TemplateResponse(
        "customer_form.html", {"request": request, "customer": None}
    )


@app.post("/customers/new")
async def create_customer(request: Request) -> RedirectResponse:
    """Handle submission of the new customer form.

    Form data is parsed asynchronously to avoid requiring the
    python‑multipart dependency.  All fields are treated as optional
    strings, with empty fields stored as None.
    """
    form = await request.form()
    name = form.get("name") or ""
    driver_license = form.get("driver_license") or None
    birth_date = form.get("birth_date") or None
    address = form.get("address") or None
    phone = form.get("phone") or None
    conn = get_db()
    conn.execute(
        "INSERT INTO customers(name, driver_license, birth_date, address, phone) VALUES (?, ?, ?, ?, ?)",
        (name, driver_license, birth_date, address, phone),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/customers", status_code=302)


@app.get("/customers/{customer_id}/edit", response_class=HTMLResponse)
def edit_customer(request: Request, customer_id: int) -> HTMLResponse:
    """Show the edit form populated with an existing customer record."""
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return templates.TemplateResponse(
        "customer_form.html", {"request": request, "customer": customer}
    )


@app.post("/customers/{customer_id}/edit")
async def update_customer(request: Request, customer_id: int) -> RedirectResponse:
    """Persist changes to an existing customer."""
    form = await request.form()
    name = form.get("name") or ""
    driver_license = form.get("driver_license") or None
    birth_date = form.get("birth_date") or None
    address = form.get("address") or None
    phone = form.get("phone") or None
    conn = get_db()
    conn.execute(
        "UPDATE customers SET name=?, driver_license=?, birth_date=?, address=?, phone=? WHERE id=?",
        (name, driver_license, birth_date, address, phone, customer_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/customers", status_code=302)


@app.post("/customers/{customer_id}/delete")
async def delete_customer(customer_id: int) -> RedirectResponse:
    """Delete a customer from the database."""
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/customers", status_code=302)


# -------------------- Order Routes --------------------

@app.get("/orders", response_class=HTMLResponse)
def list_orders(request: Request) -> HTMLResponse:
    """Display all orders in a table, joined with sender names."""
    conn = get_db()
    orders = conn.execute(
        """
        SELECT o.*, c.name AS sender_name
        FROM orders o
        LEFT JOIN customers c ON o.sender_id = c.id
        ORDER BY o.id DESC
        """
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "orders.html", {"request": request, "orders": orders}
    )


@app.get("/orders/new", response_class=HTMLResponse)
def new_order(request: Request) -> HTMLResponse:
    """Show a blank form for creating a new order."""
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    conn.close()
    return templates.TemplateResponse(
        "order_form.html",
        {"request": request, "order": None, "customers": customers},
    )


@app.post("/orders/new")
async def create_order(request: Request) -> RedirectResponse:
    """Persist a new order with computed total and unique tracking number.

    The form is parsed manually from the request to avoid requiring the
    python‑multipart package.  All numerical fields are converted to
    floats where possible; invalid values default to zero.
    """
    form = await request.form()
    sender_id = int(form.get("sender_id"))
    receiver_name = form.get("receiver_name") or ""
    receiver_address = form.get("receiver_address") or ""
    receiver_phone = form.get("receiver_phone") or ""
    # Convert numeric inputs safely
    try:
        exchange_rate = float(form.get("exchange_rate"))
    except (TypeError, ValueError):
        exchange_rate = 0.0
    try:
        amount = float(form.get("amount"))
    except (TypeError, ValueError):
        amount = 0.0
    try:
        fee = float(form.get("fee"))
    except (TypeError, ValueError):
        fee = 0.0
    send_date = form.get("send_date") or ""
    total = amount + fee
    tracking_number = str(uuid.uuid4()).split("-")[0].upper()
    status = "New"
    conn = get_db()
    conn.execute(
        """
        INSERT INTO orders(
            sender_id, receiver_name, receiver_address, receiver_phone,
            exchange_rate, amount, fee, total, send_date, tracking_number, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sender_id,
            receiver_name,
            receiver_address,
            receiver_phone,
            exchange_rate,
            amount,
            fee,
            total,
            send_date,
            tracking_number,
            status,
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/orders", status_code=302)


@app.get("/orders/{order_id}/edit", response_class=HTMLResponse)
def edit_order(request: Request, order_id: int) -> HTMLResponse:
    """Show an edit form for an existing order."""
    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    conn.close()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return templates.TemplateResponse(
        "order_form.html",
        {"request": request, "order": order, "customers": customers},
    )


@app.post("/orders/{order_id}/edit")
async def update_order(request: Request, order_id: int) -> RedirectResponse:
    """Update an existing order.  Recompute the total when amount or fee change."""
    form = await request.form()
    sender_id = int(form.get("sender_id"))
    receiver_name = form.get("receiver_name") or ""
    receiver_address = form.get("receiver_address") or ""
    receiver_phone = form.get("receiver_phone") or ""
    try:
        exchange_rate = float(form.get("exchange_rate"))
    except (TypeError, ValueError):
        exchange_rate = 0.0
    try:
        amount = float(form.get("amount"))
    except (TypeError, ValueError):
        amount = 0.0
    try:
        fee = float(form.get("fee"))
    except (TypeError, ValueError):
        fee = 0.0
    send_date = form.get("send_date") or ""
    status = form.get("status") or "New"
    total = amount + fee
    conn = get_db()
    conn.execute(
        """
        UPDATE orders
        SET sender_id=?, receiver_name=?, receiver_address=?, receiver_phone=?,
            exchange_rate=?, amount=?, fee=?, total=?, send_date=?, status=?
        WHERE id=?
        """,
        (
            sender_id,
            receiver_name,
            receiver_address,
            receiver_phone,
            exchange_rate,
            amount,
            fee,
            total,
            send_date,
            status,
            order_id,
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/orders", status_code=302)


@app.post("/orders/{order_id}/delete")
async def delete_order(order_id: int) -> RedirectResponse:
    """Delete an order from the database."""
    conn = get_db()
    conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/orders", status_code=302)


@app.get("/orders/{order_id}/pdf")
def order_pdf(order_id: int):
    """Generate and return a PDF receipt for a specific order.

    The PDF includes sender and receiver details, financial figures,
    and the order’s tracking number and date.  The output uses a
    simple 4×6 inch layout to fit standard thermal printers.
    """
    conn = get_db()
    order = conn.execute(
        """
        SELECT o.*, c.name AS sender_name, c.driver_license AS sender_driver_license,
               c.birth_date AS sender_birth_date, c.address AS sender_address,
               c.phone AS sender_phone
        FROM orders o
        LEFT JOIN customers c ON o.sender_id = c.id
        WHERE o.id=?
        """,
        (order_id,),
    ).fetchone()
    conn.close()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    pdf_bytes = generate_order_pdf(order)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=order_{order['tracking_number']}.pdf",
        },
    )


# -------------------- Tracking Routes --------------------

@app.get("/track", response_class=HTMLResponse)
def track_page(request: Request, number: str | None = None) -> HTMLResponse:
    """Display the tracking form and optionally the result if a number is provided."""
    result = None
    if number:
        conn = get_db()
        result = conn.execute(
            """
            SELECT o.*, c.name AS sender_name
            FROM orders o
            LEFT JOIN customers c ON o.sender_id = c.id
            WHERE o.tracking_number = ?
            """,
            (number,),
        ).fetchone()
        conn.close()
    return templates.TemplateResponse(
        "track.html", {"request": request, "result": result}
    )


def generate_order_pdf(order: sqlite3.Row) -> bytes:
    """Create a 4×6 inch PDF receipt for the given order.

    A new image is drawn with Pillow and then saved as a PDF.  The
    layout is intentionally simple and compact, using clear fonts
    available on the system.  Lines and headings help delineate
    sections.  The resulting bytes are returned to the caller.
    """
    # Define the output dimensions.  Using 200 DPI provides good
    # resolution while keeping file size modest (4 inches × 200 = 800
    # pixels; 6 inches × 200 = 1200 pixels).
    dpi = 200
    width_in, height_in = 4, 6
    width_px, height_px = int(width_in * dpi), int(height_in * dpi)
    img = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(img)

    # Load fonts.  If the bold font isn’t available the normal font
    # will still work.  Using try/except ensures the PDF still
    # generates on systems lacking these fonts.
    try:
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32
        )
        font_section = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24
        )
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20
        )
    except Exception:
        # Fallback to default fonts if truetype fonts aren’t available
        font_title = font_section = font = ImageFont.load_default()

    # Helper to advance vertical position with a consistent line height
    y = 20
    line_spacing = 28

    def draw_text(x: int, text: str, font_obj: ImageFont.FreeTypeFont, align: str = "left") -> None:
        nonlocal y
        # Compute position based on alignment
        if align == "center":
            text_width, _ = draw.textlength(text, font=font_obj), 0
            x_pos = (width_px - text_width) // 2
        elif align == "right":
            text_width, _ = draw.textlength(text, font=font_obj), 0
            x_pos = width_px - x - text_width
        else:
            x_pos = x
        draw.text((x_pos, y), text, font=font_obj, fill="black")
        y += line_spacing

    # Header
    draw_text(0, "VUACHUYENHANG.COM", font_title, align="center")
    draw.line((40, y, width_px - 40, y), fill="black", width=2)
    y += 15

    # Tracking number and date
    draw_text(40, f"Tracking: {order['tracking_number']}", font, align="left")
    draw_text(40, f"Date: {order['send_date']}", font, align="left")
    y += 10

    # Sender section
    draw_text(40, "Sender", font_section, align="left")
    draw_text(60, f"Name: {order['sender_name']}", font, align="left")
    draw_text(60, f"License: {order['sender_driver_license'] or ''}", font, align="left")
    draw_text(60, f"Birth: {order['sender_birth_date'] or ''}", font, align="left")
    draw_text(60, f"Address: {order['sender_address'] or ''}", font, align="left")
    draw_text(60, f"Phone: {order['sender_phone'] or ''}", font, align="left")
    y += 10

    # Receiver section
    draw_text(40, "Receiver", font_section, align="left")
    draw_text(60, f"Name: {order['receiver_name']}", font, align="left")
    draw_text(60, f"Address: {order['receiver_address']}", font, align="left")
    draw_text(60, f"Phone: {order['receiver_phone']}", font, align="left")
    y += 10

    # Details section
    draw_text(40, "Details", font_section, align="left")
    draw_text(60, f"Exchange rate: {order['exchange_rate']}", font, align="left")
    draw_text(60, f"Amount: {order['amount']}", font, align="left")
    draw_text(60, f"Fee: {order['fee']}", font, align="left")
    draw_text(60, f"Total: {order['total']}", font, align="left")
    draw_text(60, f"Status: {order['status']}", font, align="left")

    # Save to PDF into an in‑memory buffer
    buf = io.BytesIO()
    # 72 DPI is the default resolution for PDF; specifying resolution
    # ensures the PDF dimensions correspond to inches.  The PDF
    # generator will convert pixel sizes into points (1/72 inch).
    img.save(buf, format="PDF", resolution=dpi)
    return buf.getvalue()