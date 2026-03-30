import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, current_user, logout_user, login_required
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

# Importamos los modelos base
from models import db, User, Producto, Pedido, ItemPedido 

app = Flask(__name__)

# --- CONFIGURACIÓN DE SEGURIDAD ---
# Usa la variable de entorno de Render o una por defecto para desarrollo
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "tu_llave_secreta_aqui")

# --- CONFIGURACIÓN DE BASE DE DATOS (OPTIMIZADA PARA RENDER) ---
uri = os.environ.get("DATABASE_URL", "sqlite:///moda360.db")

# Corrección para SQLAlchemy 1.4+ (Render entrega postgres:// y se requiere postgresql://)
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURACIÓN DE CARGA DE IMÁGENES ---
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'productos')
PAYMENTS_FOLDER = os.path.join('static', 'uploads', 'comprobantes')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PAYMENTS_FOLDER'] = PAYMENTS_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Asegurar que las carpetas existan en el servidor
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PAYMENTS_FOLDER, exist_ok=True)

# --- MODELO DE PAGOS (DEFINICIÓN) ---
class PagoNotificado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    referencia = db.Column(db.String(100), nullable=False)
    comprobante_url = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.String(20), default='pendiente') # pendiente, aprobado, rechazado
    fecha_notificacion = db.Column(db.DateTime, default=datetime.utcnow)

    pedido = db.relationship('Pedido', backref=db.backref('pagos_pendientes', lazy=True))
    usuario = db.relationship('User', backref=db.backref('mis_pagos', lazy=True))

# --- INICIALIZACIÓN DE EXTENSIONES ---
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Por favor inicia sesión para acceder."
login_manager.login_message_category = "danger"

# --- BLOQUE CRÍTICO: CREACIÓN DE TABLAS EN RENDER ---
# Al no tener Shell, esto crea la BD de Postgres apenas el sistema detecta la conexión
with app.app_context():
    try:
        db.create_all()
        print("Base de datos e infraestructuras creadas exitosamente.")
    except Exception as e:
        print(f"Aviso en creación de tablas: {e}")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- RUTAS PRINCIPALES ---

@app.route('/')
def home():
    productos = Producto.query.filter(Producto.stock_fisico > 0).all()
    todos_los_clientes = []
    if current_user.is_authenticated and current_user.es_admin:
        todos_los_clientes = User.query.filter_by(es_admin=False).all()
    return render_template('home.html', productos=productos, todos_los_clientes=todos_los_clientes)

# --- RUTAS DE AUTENTICACIÓN ---

@app.route("/registro", methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_admin' if current_user.es_admin else 'dashboard_cliente'))
    
    if request.method == 'POST':
        try:
            hashed_pw = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
            user = User(
                username=request.form['telefono'],
                email=request.form.get('email', ''),
                password=hashed_pw,
                first_name=request.form['nombre'],
                last_name=request.form['apellido'],
                telefono=request.form['telefono'],
                es_admin=False
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Cuenta creada con éxito', 'success')
            return redirect(url_for('dashboard_cliente'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: El número ya existe o datos inválidos.', 'danger')
            
    return render_template('registro.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_admin' if current_user.es_admin else 'dashboard_cliente'))
        
    if request.method == 'POST':
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        user = User.query.filter_by(username=telefono).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            flash(f'Bienvenido, {user.first_name}', 'success')
            return redirect(url_for('dashboard_admin' if user.es_admin else 'dashboard_cliente'))
        else:
            flash('Login fallido. Revisa el teléfono y la clave', 'danger')
            
    return render_template('login.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('home'))

# --- DASHBOARDS ---

@app.route("/mi-cuenta")
@login_required
def dashboard_cliente():
    if current_user.es_admin:
        return redirect(url_for('dashboard_admin'))
    pedidos = Pedido.query.filter_by(usuario_id=current_user.id).order_by(Pedido.id.desc()).all()
    return render_template('dashboard_cliente.html', user=current_user, pedidos=pedidos)

@app.route('/admin/dashboard')
@login_required
def dashboard_admin():
    if not current_user.es_admin:
        flash('Acceso restringido.', 'danger')
        return redirect(url_for('home'))
    
    total_usuarios = User.query.count()
    productos = Producto.query.all()
    valor_inventario = sum((p.precio_costo or 0) * (p.stock_fisico or 0) for p in productos)
    clientes_deudores = User.query.filter(User.deuda_total > 0).all()
    total_deuda_global = sum(cliente.deuda_total for cliente in clientes_deudores)
    pagos_pendientes = PagoNotificado.query.filter_by(estado='pendiente').all()
    
    return render_template('dashboard_admin.html', 
                           user=current_user, 
                           total_users=total_usuarios, 
                           productos=productos,
                           clientes_deudores=clientes_deudores,
                           total_deuda_global=total_deuda_global,
                           valor_inventario=valor_inventario,
                           pagos_pendientes=pagos_pendientes)

# --- LÓGICA DE CARRITO Y PEDIDOS ---

@app.route("/añadir-al-carrito/<int:producto_id>", methods=['POST'])
@login_required
def añadir_al_carrito(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    
    if current_user.es_admin:
        target_user_id = request.form.get('cliente_id')
        if not target_user_id:
            flash('Error: Debes seleccionar un cliente.', 'danger')
            return redirect(url_for('home'))
        nuevo_estado = 'confirmado'
    else:
        target_user_id = current_user.id
        nuevo_estado = 'por confirmar'

    try:
        pedido = Pedido.query.filter_by(usuario_id=target_user_id, estado=nuevo_estado).first()
        if not pedido:
            pedido = Pedido(usuario_id=target_user_id, estado=nuevo_estado, total_a_pagar=0.0)
            db.session.add(pedido)
            db.session.flush()

        item = ItemPedido.query.filter_by(pedido_id=pedido.id, producto_id=producto.id).first()
        if item:
            item.cantidad += 1
        else:
            item = ItemPedido(
                pedido_id=pedido.id,
                producto_id=producto.id,
                cantidad=1,
                precio_unitario=producto.precio_final
            )
            db.session.add(item)

        pedido.total_a_pagar += producto.precio_final
        if producto.stock_fisico > 0:
            producto.stock_fisico -= 1
        
        db.session.commit()
        flash("Asignado correctamente." if current_user.es_admin else f"{producto.nombre} añadido.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar: {str(e)}', 'danger')

    return redirect(url_for('home'))

# --- NUEVA LÓGICA DE PAGOS ---

@app.route("/registrar_pago", methods=['POST'])
@login_required
def registrar_pago():
    try:
        pedido_id = request.form.get('pedido_id')
        monto = float(request.form.get('monto') or 0)
        referencia = request.form.get('referencia')
        file = request.files.get('comprobante')

        if not file or file.filename == '':
            flash('Debes adjuntar el comprobante.', 'warning')
            return redirect(url_for('dashboard_cliente'))

        pedido = Pedido.query.get_or_404(pedido_id)
        filename = secure_filename(f"REF_{referencia}_{file.filename}")
        file.save(os.path.join(app.config['PAYMENTS_FOLDER'], filename))
        
        nuevo_pago = PagoNotificado(
            pedido_id=pedido.id,
            usuario_id=current_user.id,
            monto=monto,
            referencia=referencia,
            comprobante_url=filename,
            estado='pendiente'
        )
        db.session.add(nuevo_pago)
        db.session.commit()
        flash(f'Notificación enviada. Referencia: {referencia}.', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('dashboard_cliente'))

@app.route("/admin/validar-pago/<int:pago_id>/<string:accion>", methods=['POST'])
@login_required
def validar_pago(pago_id, accion):
    if not current_user.es_admin:
        return jsonify({"error": "No autorizado"}), 403
    
    pago = PagoNotificado.query.get_or_404(pago_id)
    try:
        if accion == 'aprobar':
            pago.estado = 'aprobado'
            pago.pedido.monto_pagado += pago.monto
            flash(f"Pago aprobado.", "success")
        elif accion == 'rechazar':
            pago.estado = 'rechazado'
            flash(f"Pago rechazado.", "warning")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for('dashboard_admin'))

# --- INICIO DE APLICACIÓN ---
if __name__ == '__main__':
    # El debug se puede apagar en producción cambiando a False
    app.run(debug=False)
