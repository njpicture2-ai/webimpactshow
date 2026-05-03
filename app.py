import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import secrets
from io import BytesIO
from html2image import Html2Image
import tempfile
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import pytz

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Utiliser SQLite local si PostgreSQL est indisponible
_pg_url = os.environ.get('DATABASE_URL')
_sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webimpact.db')
_sqlite_url = f'sqlite:///{_sqlite_path}'

def _test_pg_connection(url):
    if not url:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False

_use_sqlite = not _test_pg_connection(_pg_url)
if _use_sqlite:
    print("⚠️  PostgreSQL indisponible - utilisation de SQLite local")
    app.config['SQLALCHEMY_DATABASE_URI'] = _sqlite_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'connect_args': {'check_same_thread': False},
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = _pg_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_size': 10,
        'max_overflow': 20,
    }
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Fonction Jinja2 pour formater les dates en heure de Lubumbashi
@app.template_filter('lubumbashi_datetime')
def lubumbashi_datetime_filter(dt, format='%d/%m/%Y à %H:%M'):
    """Filtre Jinja2 pour afficher les dates au fuseau horaire de Lubumbashi"""
    if dt is None:
        return ''
    dt_lubumbashi = convert_to_lubumbashi(dt)
    return dt_lubumbashi.strftime(format)

@app.template_filter('lubumbashi_time')
def lubumbashi_time_filter(dt, format='%H:%M:%S'):
    """Filtre Jinja2 pour afficher l'heure au fuseau horaire de Lubumbashi"""
    if dt is None:
        return ''
    dt_lubumbashi = convert_to_lubumbashi(dt)
    return dt_lubumbashi.strftime(format)

ADMIN_PASSWORD = "IRJOHNK"

LUBUMBASHI_TZ = pytz.timezone('Africa/Lubumbashi')

def get_lubumbashi_time():
    """Retourne l'heure actuelle de Lubumbashi (CAT = UTC+2)"""
    return datetime.now(LUBUMBASHI_TZ)

def get_lubumbashi_date():
    """Retourne la date actuelle de Lubumbashi"""
    return get_lubumbashi_time().date()

def convert_to_lubumbashi(dt):
    """Convertit une datetime en fuseau horaire de Lubumbashi"""
    if dt is None:
        return None
    
    # Si la date est naive (sans timezone), on assume qu'elle est en UTC
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convertir au fuseau horaire de Lubumbashi
    return dt.astimezone(LUBUMBASHI_TZ)

PACKAGES = [
    {"id": "standard", "name": "STANDARD", "price": "2500 FC", "votes": 5, "url": "https://njpicture.mychariow.com/prd_bfhpfo/checkout"},
    {"id": "basic", "name": "BASIC", "price": "5000 FC", "votes": 12, "url": "https://njpicture.mychariow.com/prd_ud9hkt/checkout"},
    {"id": "classic", "name": "CLASSIC", "price": "10000 FC", "votes": 26, "url": "https://njpicture.mychariow.com/prd_rft2j1/checkout"},
    {"id": "special", "name": "SPÉCIAL", "price": "20000 FC", "votes": 54, "url": "https://njpicture.mychariow.com/prd_aw8vv6/checkout"},
    {"id": "premium", "name": "PREMIUM", "price": "115000 FC (50$)", "votes": 310, "url": "https://njpicture.mychariow.com/prd_wn4kik/checkout"},
    {"id": "vip", "name": "VIP", "price": "230000 FC (100$)", "votes": 625, "url": "https://njpicture.mychariow.com/prd_41xu63/checkout"},
    {"id": "diamant", "name": "BOUQUET DIAMANT", "price": "560000 FC (200$)", "votes": 1252, "url": "https://njpicture.mychariow.shop/prd_bxu8hk/checkout"},
    {"id": "or", "name": "BOUQUET OR", "price": "1000000 FC", "votes": 2510, "url": "https://njpicture.mychariow.shop/prd_fc495p/checkout"}
]

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)
    
class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    photo_data = db.Column(db.LargeBinary)
    photo_filename = db.Column(db.String(200))
    vote_count = db.Column(db.Integer, default=0)
    is_eliminated = db.Column(db.Boolean, default=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)
    
    category = db.relationship('Category', backref='candidates')

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'), nullable=False)
    votes_count = db.Column(db.Integer, default=1)
    invoice_number = db.Column(db.String(4), unique=True)
    amount_paid = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    package_id = db.Column(db.String(50), nullable=False)
    votes_purchased = db.Column(db.Integer, nullable=False)
    votes_remaining = db.Column(db.Integer, nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'))
    session_token = db.Column(db.String(100), unique=True)
    is_used = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)

class SiteVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    visit_date = db.Column(db.Date, default=get_lubumbashi_date)
    visit_count = db.Column(db.Integer, default=1)

class VotingStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_open = db.Column(db.Boolean, default=True)
    votes_hidden = db.Column(db.Boolean, default=False)

class WhatsAppStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=True)

class ChristmasHatStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, default=True)

class LaureatesVisibility(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_visible = db.Column(db.Boolean, default=True)

class Laureate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'), nullable=False)
    vote_count = db.Column(db.Integer, default=0)
    position = db.Column(db.Integer, default=1)
    synced_at = db.Column(db.DateTime, default=get_lubumbashi_time)
    
    category = db.relationship('Category', backref='laureates')
    candidate = db.relationship('Candidate', backref='laureate_entry')

class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    photo_data = db.Column(db.LargeBinary)
    photo_filename = db.Column(db.String(200))
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)

class Partner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_data = db.Column(db.LargeBinary)
    logo_filename = db.Column(db.String(200))
    website_url = db.Column(db.String(300))
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    group_name = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)
    
    @property
    def group_icon(self):
        """Retourne l'icône du domaine"""
        icons = {
            'INFLUENCEURS & COMMUNICATION DIGITALE': '🎯',
            'REALISATION VISUEL & CINÉMATOGRAPHIQUE': '🎬',
            'ARTS VISUELS & DESIGN NUMÉRIQUE': '📸',
            'JOURNALISME & ANALYSE DIGITALE': '📰',
            'ENTREPRENEURIAT & INNOVATION DIGITALE': '💡',
            'SPIRITUALITÉ & IMPACT SOCIAL': '✨'
        }
        return icons.get(self.group_name, '📁')

class DailyVoteStatistics(db.Model):
    """Statistiques quotidiennes archivées pour garder l'historique des votes"""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    total_votes = db.Column(db.Integer, default=0)
    total_transactions = db.Column(db.Integer, default=0)
    total_amount_fc = db.Column(db.Integer, default=0)
    total_users = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_lubumbashi_time)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_invoice_number():
    """Génère un numéro de facture unique à 4 chiffres"""
    import random
    while True:
        invoice_num = str(random.randint(1000, 9999))
        existing = Vote.query.filter_by(invoice_number=invoice_num).first()
        if not existing:
            return invoice_num

def get_package_amount(package_id):
    """Retourne le montant en FC selon le package ID"""
    package_prices = {
        'standard': 2500,
        'basic': 5000,
        'classic': 10000,
        'special': 20000,
        'premium': 115000,
        'vip': 230000,
        'diamant': 560000,
        'or': 1000000
    }
    return package_prices.get(package_id, 0)

def archive_daily_statistics(target_date=None):
    """Archive les statistiques d'une journée spécifique (par défaut : hier)"""
    try:
        if target_date is None:
            # Par défaut, archiver les stats d'hier
            target_date = get_lubumbashi_date() - timedelta(days=1)
        
        # Vérifier si les stats existent déjà pour cette date
        existing_stats = DailyVoteStatistics.query.filter_by(date=target_date).first()
        if existing_stats:
            return existing_stats
        
        # Calculer les statistiques de la journée
        start_datetime = datetime.combine(target_date, datetime.min.time())
        end_datetime = datetime.combine(target_date, datetime.max.time())
        
        # Convertir en fuseau horaire de Lubumbashi
        start_datetime = LUBUMBASHI_TZ.localize(start_datetime)
        end_datetime = LUBUMBASHI_TZ.localize(end_datetime)
        
        # Compter les votes de cette journée
        daily_votes = Vote.query.filter(
            Vote.created_at >= start_datetime,
            Vote.created_at <= end_datetime
        ).all()
        
        total_votes = sum(vote.votes_count or 0 for vote in daily_votes)
        total_amount = sum(vote.amount_paid or 0 for vote in daily_votes)
        total_transactions = len(daily_votes)
        
        # Compter les utilisateurs uniques de cette journée
        unique_users = db.session.query(Vote.user_id).filter(
            Vote.created_at >= start_datetime,
            Vote.created_at <= end_datetime
        ).distinct().count()
        
        # Créer l'enregistrement
        stats = DailyVoteStatistics(
            date=target_date,
            total_votes=total_votes,
            total_transactions=total_transactions,
            total_amount_fc=total_amount,
            total_users=unique_users
        )
        db.session.add(stats)
        db.session.commit()
        
        return stats
    except Exception as e:
        print(f"Erreur dans archive_daily_statistics : {e}")
        db.session.rollback()
        return None

_partners_cache = None
_partners_cache_time = None
_last_archive_check = None
_candidates_cache = None
_candidates_cache_time = None
_categories_cache = None
_categories_cache_time = None
_users_cache = {}
_voting_status_cache = None
_voting_status_cache_time = None

@app.context_processor
def inject_partners():
    """Injecte les partenaires avec cache de 5 minutes pour améliorer la performance"""
    global _partners_cache, _partners_cache_time
    
    now = datetime.now()
    if _partners_cache is None or _partners_cache_time is None or (now - _partners_cache_time).seconds > 300:
        _partners_cache = Partner.query.filter_by(is_active=True).order_by(Partner.order).all()
        _partners_cache_time = now
    
    whatsapp_status = WhatsAppStatus.query.first()
    is_whatsapp_active = whatsapp_status.is_active if whatsapp_status else True
    
    christmas_hat_status = ChristmasHatStatus.query.first()
    is_christmas_hat_active = christmas_hat_status.is_active if christmas_hat_status else True
    
    laureates_visibility = LaureatesVisibility.query.first()
    is_laureates_visible = laureates_visibility.is_visible if laureates_visibility else True
    
    return dict(active_partners=_partners_cache, is_whatsapp_active=is_whatsapp_active, is_christmas_hat_active=is_christmas_hat_active, is_laureates_visible=is_laureates_visible)

@app.after_request
def add_cache_headers(response):
    """Ajoute des en-têtes de cache pour accélérer le chargement"""
    if request.endpoint and 'static' in request.endpoint:
        response.cache_control.max_age = 31536000
        response.cache_control.public = True
    elif request.endpoint in ['candidate_photo', 'partner_logo', 'team_member_photo']:
        response.cache_control.max_age = 3600
        response.cache_control.public = True
    return response

@app.after_request
def compress_response(response):
    """Compression GZIP pour connexions lentes - réduit la taille de 70-80%"""
    accept_encoding = request.headers.get('Accept-Encoding', '')
    
    if 'gzip' not in accept_encoding.lower():
        return response
    
    if (response.status_code < 200 or 
        response.status_code >= 300 or 
        response.direct_passthrough or
        'Content-Encoding' in response.headers):
        return response
    
    # Compresser seulement le HTML, CSS, JS, JSON
    content_type = response.headers.get('Content-Type', '')
    if not any(ct in content_type for ct in ['text/html', 'text/css', 'text/javascript', 
                                               'application/json', 'application/javascript']):
        return response
    
    # Compression GZIP aggressive
    import gzip
    from io import BytesIO
    
    gzip_buffer = BytesIO()
    gzip_file = gzip.GzipFile(mode='wb', compresslevel=9, fileobj=gzip_buffer)
    gzip_file.write(response.get_data())
    gzip_file.close()
    
    response.set_data(gzip_buffer.getvalue())
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = len(response.get_data())
    response.headers['Vary'] = 'Accept-Encoding'
    
    return response

@app.after_request
def add_performance_headers(response):
    """Headers de performance pour ouverture ultra-rapide"""
    # Préchargement DNS pour ressources externes
    response.headers['X-DNS-Prefetch-Control'] = 'on'
    
    # Sécurité de base
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    
    return response

# Minification HTML désactivée pour éviter de casser le JavaScript
# La compression GZIP (70-80% de réduction) est largement suffisante

@app.before_request
def auto_archive_stats():
    """Archive automatiquement TOUS les jours manquants (optimisé pour ne vérifier qu'une fois par heure)"""
    global _last_archive_check
    
    if request.endpoint and 'static' not in request.endpoint:
        now = datetime.now()
        
        if _last_archive_check is None or (now - _last_archive_check).seconds > 3600:
            _last_archive_check = now
            try:
                # Trouver le premier vote pour déterminer la date de début
                first_vote = Vote.query.order_by(Vote.created_at).first()
                if first_vote:
                    # Date de début = date du premier vote
                    start_date = first_vote.created_at.date()
                    # Date de fin = hier (on n'archive pas aujourd'hui)
                    end_date = get_lubumbashi_date() - timedelta(days=1)
                    
                    # Parcourir tous les jours et archiver ceux qui manquent
                    current_date = start_date
                    while current_date <= end_date:
                        existing = DailyVoteStatistics.query.filter_by(date=current_date).first()
                        if not existing:
                            # Archiver ce jour (même avec 0 votes)
                            archive_daily_statistics(current_date)
                        current_date += timedelta(days=1)
            except Exception as e:
                print(f"Erreur auto_archive_stats: {e}")
                pass

def get_cached_candidates():
    """Retourne les candidats avec cache de 30 secondes pour navigation ultra-rapide"""
    global _candidates_cache, _candidates_cache_time
    now = datetime.now()
    if _candidates_cache is None or _candidates_cache_time is None or (now - _candidates_cache_time).seconds > 30:
        _candidates_cache = Candidate.query.options(joinedload(Candidate.category)).order_by(Candidate.number).all()
        _candidates_cache_time = now
    return _candidates_cache

def get_cached_categories():
    """Retourne les catégories avec cache de 5 minutes pour navigation ultra-rapide"""
    global _categories_cache, _categories_cache_time
    now = datetime.now()
    if _categories_cache is None or _categories_cache_time is None or (now - _categories_cache_time).seconds > 300:
        _categories_cache = Category.query.order_by(Category.order).all()
        _categories_cache_time = now
    return _categories_cache

def get_cached_user(user_id):
    """Cache des utilisateurs pour éviter les requêtes DB répétées"""
    global _users_cache
    if user_id not in _users_cache:
        user = db.session.get(User, user_id)
        _users_cache[user_id] = user
    return _users_cache[user_id]

def get_cached_voting_status():
    """Cache du statut de vote pour réduire les requêtes DB"""
    global _voting_status_cache, _voting_status_cache_time
    now = datetime.now()
    if _voting_status_cache is None or _voting_status_cache_time is None or (now - _voting_status_cache_time).seconds > 60:
        _voting_status_cache = VotingStatus.query.first()
        _voting_status_cache_time = now
    return _voting_status_cache

@app.route('/laureates')
def laureates():
    """Page des lauréats - affiche le gagnant de chaque catégorie"""
    laureates_list = Laureate.query.all()
    
    # Grouper les lauréats par domaine
    grouped_laureates = {}
    for laureate in laureates_list:
        group_name = laureate.category.group_name if laureate.category else "Autre"
        if group_name not in grouped_laureates:
            grouped_laureates[group_name] = []
        grouped_laureates[group_name].append(laureate)
    
    # Récupérer la dernière synchronisation
    last_sync = None
    if laureates_list:
        last_sync = max(l.synced_at for l in laureates_list if l.synced_at)
    
    whatsapp_status = WhatsAppStatus.query.first()
    is_whatsapp_active = whatsapp_status.is_active if whatsapp_status else True
    
    return render_template('laureates.html', 
                         grouped_laureates=grouped_laureates,
                         last_sync=last_sync,
                         is_whatsapp_active=is_whatsapp_active)

@app.route('/')
def index():
    # Gérer le retour de Chariow avec ?purchase=SALEID
    purchase_id = request.args.get('purchase')
    if purchase_id and 'pending_transaction_token' in session:
        # Chercher LA transaction spécifique de l'utilisateur
        transaction = Transaction.query.filter_by(
            session_token=session['pending_transaction_token'],
            is_verified=False
        ).first()
        
        if transaction:
            # Vérifier que le vote est ouvert
            voting_status = VotingStatus.query.first()
            is_voting_open = voting_status.is_open if voting_status else True
            
            if not is_voting_open:
                flash('⚠️ Le vote est actuellement fermé. Votre paiement a été enregistré mais les votes ne peuvent pas être attribués pour le moment.', 'warning')
                session.pop('pending_transaction_token', None)
                session.pop('pending_package_name', None)
                session.pop('pending_votes', None)
                return redirect(url_for('index'))
            
            # Récupérer le candidat
            candidate = Candidate.query.get(transaction.candidate_id)
            
            if not candidate or candidate.is_eliminated:
                flash('⚠️ Le candidat sélectionné n\'est plus disponible. Contactez le support.', 'error')
                session.pop('pending_transaction_token', None)
                session.pop('pending_package_name', None)
                session.pop('pending_votes', None)
                return redirect(url_for('index'))
            
            # ATTRIBUER AUTOMATIQUEMENT LES VOTES AU CANDIDAT
            votes_to_add = transaction.votes_purchased
            candidate.vote_count += votes_to_add
            
            # Marquer la transaction comme utilisée
            transaction.votes_remaining = 0
            transaction.is_verified = True
            transaction.is_used = True
            
            # Générer un numéro de facture unique
            invoice_num = generate_invoice_number()
            amount = get_package_amount(transaction.package_id)
            
            # Créer l'enregistrement du vote
            vote_record = Vote(
                user_id=transaction.user_id,
                candidate_id=transaction.candidate_id,
                votes_count=votes_to_add,
                invoice_number=invoice_num,
                amount_paid=amount
            )
            db.session.add(vote_record)
            db.session.commit()
            
            # Restaurer la session de l'utilisateur
            session['user_id'] = transaction.user_id
            
            # Stocker les informations pour la page de reçu
            session['last_vote_candidate_id'] = transaction.candidate_id
            session['last_vote_count'] = votes_to_add
            session['last_invoice_number'] = invoice_num
            session['last_amount_paid'] = amount
            
            # Nettoyer les sessions en attente
            session.pop('pending_transaction_token', None)
            session.pop('pending_package_name', None)
            session.pop('pending_votes', None)
            session.pop('transaction_token', None)
            session.pop('selected_candidate_id', None)
            
            # Invalider le cache des candidats pour afficher les nouveaux votes
            global _candidates_cache
            _candidates_cache = None
            
            # Rediriger DIRECTEMENT vers la page de reçu
            return redirect(url_for('vote_success'))
    
    # Rediriger vers l'inscription si l'utilisateur n'est pas connecté
    if 'user_id' not in session:
        return redirect(url_for('register'))
    
    today = get_lubumbashi_date()
    visit = SiteVisit.query.filter_by(visit_date=today).first()
    if not visit:
        visit = SiteVisit(visit_date=today, visit_count=1)
        db.session.add(visit)
    else:
        visit.visit_count += 1
    db.session.commit()
    
    candidates = get_cached_candidates()
    user = get_cached_user(session['user_id'])
    
    voting_status = get_cached_voting_status()
    is_voting_open = voting_status.is_open if voting_status else True
    
    active_transaction = None
    if 'transaction_token' in session:
        active_transaction = Transaction.query.filter_by(
            session_token=session['transaction_token'],
            is_used=False
        ).first()
    
    categories = get_cached_categories()
    
    return render_template('index.html', 
                         candidates=candidates, 
                         user=user,
                         is_voting_open=is_voting_open,
                         voting_status=voting_status,
                         active_transaction=active_transaction,
                         categories=categories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            
            if not full_name or not phone:
                flash('⚠️ Veuillez remplir tous les champs', 'error')
                return render_template('register.html')
            
            # Créer l'utilisateur (ZÉRO restrictions - comptes illimités autorisés)
            user = User(full_name=full_name, phone=phone)
            db.session.add(user)
            db.session.commit()
            
            # Créer la session permanente
            session.permanent = True
            session['user_id'] = user.id
            
            return redirect(url_for('index'))
            
        except Exception as e:
            db.session.rollback()
            print(f"ERREUR CONNEXION: {str(e)}")
            flash('❌ Erreur lors de la connexion. Veuillez réessayer.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/about')
def about():
    team_members = TeamMember.query.order_by(TeamMember.order).all()
    return render_template('about.html', team_members=team_members)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/select_package/<int:candidate_id>')
def select_package(candidate_id):
    if 'user_id' not in session:
        return redirect(url_for('register'))
    
    # ULTRA-RAPIDE : Utiliser le cache au lieu de DB
    cached_candidates = get_cached_candidates()
    candidate = next((c for c in cached_candidates if c.id == candidate_id), None)
    
    if not candidate:
        # Fallback uniquement si pas dans le cache
        candidate = Candidate.query.get_or_404(candidate_id)
    
    # Sauvegarder dans la session IMMÉDIATEMENT
    session['selected_candidate_id'] = candidate_id
    
    # Retourner la page DIRECTEMENT avec cache
    response = make_response(render_template('select_package.html', candidate=candidate, packages=PACKAGES))
    # Pas de cache HTTP pour cette page (toujours fraîche)
    response.cache_control.no_cache = True
    response.cache_control.no_store = True
    response.cache_control.must_revalidate = True
    return response

@app.route('/payment/<package_id>')
def payment(package_id):
    if 'user_id' not in session or 'selected_candidate_id' not in session:
        return redirect(url_for('index'))
    
    package = next((p for p in PACKAGES if p['id'] == package_id), None)
    if not package:
        return redirect(url_for('index'))
    
    session_token = secrets.token_urlsafe(32)
    transaction = Transaction(
        user_id=session['user_id'],
        package_id=package_id,
        votes_purchased=package['votes'],
        votes_remaining=0,
        candidate_id=session['selected_candidate_id'],
        session_token=session_token
    )
    db.session.add(transaction)
    db.session.commit()
    
    session['pending_transaction_token'] = session_token
    session['pending_package_name'] = package['name']
    session['pending_votes'] = package['votes']
    
    return redirect(package['url'])

@app.route('/payment_confirm')
def payment_confirm():
    if 'pending_transaction_token' not in session:
        return redirect(url_for('index'))
    
    package_name = session.get('pending_package_name', 'Inconnu')
    votes_count = session.get('pending_votes', 0)
    
    return render_template('payment_confirm.html', 
                         package_name=package_name,
                         votes_count=votes_count)

@app.route('/payment_return')
def payment_return():
    if 'pending_transaction_token' not in session:
        flash('Session de paiement invalide', 'error')
        return redirect(url_for('index'))
    
    payment_success = request.args.get('success')
    
    if payment_success is None:
        flash('Statut de paiement non spécifié', 'error')
        return redirect(url_for('index'))
    
    transaction = Transaction.query.filter_by(
        session_token=session['pending_transaction_token']
    ).first()
    
    if not transaction:
        flash('Transaction non trouvée', 'error')
        return redirect(url_for('index'))
    
    if payment_success.lower() == 'true':
        transaction.votes_remaining = transaction.votes_purchased
        transaction.is_verified = True
        db.session.commit()
        
        session['transaction_token'] = session['pending_transaction_token']
        session.pop('pending_transaction_token', None)
        session.pop('pending_package_name', None)
        session.pop('pending_votes', None)
        
        flash('Paiement confirmé! Vous pouvez maintenant voter.', 'success')
    else:
        db.session.delete(transaction)
        db.session.commit()
        
        session.pop('pending_transaction_token', None)
        session.pop('pending_package_name', None)
        session.pop('pending_votes', None)
        session.pop('selected_candidate_id', None)
        
        flash('Paiement annulé ou échoué', 'error')
    
    return redirect(url_for('index'))

@app.route('/vote/<int:candidate_id>', methods=['POST'])
def vote(candidate_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Non connecté'}), 401
    
    voting_status = VotingStatus.query.first()
    if voting_status and not voting_status.is_open:
        return jsonify({'success': False, 'message': 'Le vote est fermé'}), 403
    
    if 'transaction_token' not in session:
        return jsonify({'success': False, 'message': 'Aucun vote disponible'}), 403
    
    transaction = Transaction.query.filter_by(
        session_token=session['transaction_token'],
        is_used=False
    ).first()
    
    if not transaction or transaction.votes_remaining <= 0:
        return jsonify({'success': False, 'message': 'Aucun vote disponible'}), 403
    
    if transaction.candidate_id != candidate_id:
        return jsonify({'success': False, 'message': 'Candidat incorrect'}), 403
    
    candidate = Candidate.query.get_or_404(candidate_id)
    
    if candidate.is_eliminated:
        return jsonify({'success': False, 'message': 'Candidat éliminé'}), 403
    
    # Attribuer TOUS les votes en une seule fois
    votes_to_add = transaction.votes_remaining
    candidate.vote_count += votes_to_add
    transaction.votes_remaining = 0
    transaction.is_used = True
    
    # Générer un numéro de facture unique
    invoice_num = generate_invoice_number()
    amount = get_package_amount(transaction.package_id)
    
    vote_record = Vote(
        user_id=session['user_id'],
        candidate_id=candidate_id,
        votes_count=votes_to_add,
        invoice_number=invoice_num,
        amount_paid=amount
    )
    db.session.add(vote_record)
    db.session.commit()
    
    # Stocker les informations pour la page de confirmation
    session['last_vote_candidate_id'] = candidate_id
    session['last_vote_count'] = votes_to_add
    session['last_invoice_number'] = invoice_num
    session['last_amount_paid'] = amount
    
    # Nettoyer la session de transaction
    session.pop('transaction_token', None)
    session.pop('selected_candidate_id', None)
    
    return jsonify({
        'success': True, 
        'new_count': candidate.vote_count,
        'votes_added': votes_to_add,
        'votes_remaining': 0,
        'redirect_url': url_for('vote_success')
    })

@app.route('/dashboard')
def dashboard():
    total_participants = User.query.count()
    
    candidates = get_cached_candidates()
    active_candidates = [c for c in candidates if not c.is_eliminated]
    total_votes = sum(c.vote_count for c in active_candidates)
    
    top_candidate = max(active_candidates, key=lambda c: c.vote_count) if active_candidates else None
    top_4_candidates = sorted(active_candidates, key=lambda c: c.vote_count, reverse=True)[:4]
    
    return render_template('dashboard.html',
                         total_participants=total_participants,
                         total_votes=total_votes,
                         top_candidate=top_candidate,
                         top_4_candidates=top_4_candidates)

@app.route('/vote_success')
def vote_success():
    if 'user_id' not in session:
        return redirect(url_for('register'))
    
    if 'last_vote_candidate_id' not in session or 'last_vote_count' not in session:
        return redirect(url_for('index'))
    
    cached_candidates = get_cached_candidates()
    candidate = next((c for c in cached_candidates if c.id == session['last_vote_candidate_id']), None)
    if not candidate:
        candidate = Candidate.query.get_or_404(session['last_vote_candidate_id'])
    
    user = get_cached_user(session['user_id'])
    votes_cast = session['last_vote_count']
    invoice_number = session.get('last_invoice_number', '0000')
    amount_paid = session.get('last_amount_paid', 0)
    vote_date = get_lubumbashi_time()
    
    session.pop('last_vote_candidate_id', None)
    session.pop('last_vote_count', None)
    session.pop('last_invoice_number', None)
    session.pop('last_amount_paid', None)
    
    return render_template('vote_success.html',
                         candidate=candidate,
                         user=user,
                         votes_cast=votes_cast,
                         invoice_number=invoice_number,
                         amount_paid=amount_paid,
                         vote_date=vote_date)

@app.route('/demo_facture')
def demo_facture():
    """Route de démonstration pour voir la facture sans passer par le paiement"""
    # Créer des données de démonstration
    class DemoUser:
        full_name = "ISO PROFESSIONNEL"
        phone = "+243 972 502 962"
    
    class DemoCandidate:
        id = 1
        name = "ISO PROFESSIONNEL"
        
    demo_user = DemoUser()
    demo_candidate = DemoCandidate()
    
    return render_template('vote_success.html',
                         candidate=demo_candidate,
                         user=demo_user,
                         votes_cast=2500,
                         invoice_number="1234",
                         amount_paid=250000,
                         vote_date=get_lubumbashi_time())

@app.route('/test_time')
def test_time():
    """Route de test pour vérifier le fuseau horaire"""
    from datetime import datetime
    import pytz
    
    current_lubumbashi = get_lubumbashi_time()
    current_utc = datetime.now(pytz.utc)
    
    info = {
        'fuseau_lubumbashi': 'Africa/Lubumbashi (CAT = UTC+2)',
        'heure_actuelle_lubumbashi': current_lubumbashi.strftime('%d/%m/%Y à %H:%M:%S'),
        'heure_actuelle_utc': current_utc.strftime('%d/%m/%Y à %H:%M:%S'),
        'difference': '+2 heures par rapport à UTC',
        'confirmation': 'Toutes les dates dans la base de données sont enregistrées avec le fuseau horaire de Lubumbashi'
    }
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Fuseau Horaire - Lubumbashi</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}
            .box {{
                background: white;
                color: #333;
                padding: 30px;
                border-radius: 15px;
                margin: 20px 0;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }}
            h1 {{
                color: #667eea;
            }}
            .time-display {{
                font-size: 2em;
                font-weight: bold;
                color: #764ba2;
                margin: 20px 0;
            }}
            .info {{
                margin: 10px 0;
                padding: 10px;
                background: #f0f0f0;
                border-left: 4px solid #667eea;
            }}
        </style>
    </head>
    <body>
        <div class="box">
            <h1>⏰ Test du Fuseau Horaire - Lubumbashi</h1>
            
            <div class="info">
                <strong>Fuseau horaire configuré :</strong><br>
                {info['fuseau_lubumbashi']}
            </div>
            
            <div class="time-display">
                🇨🇩 Lubumbashi : {info['heure_actuelle_lubumbashi']}
            </div>
            
            <div class="time-display">
                🌍 UTC : {info['heure_actuelle_utc']}
            </div>
            
            <div class="info">
                <strong>Différence :</strong> {info['difference']}
            </div>
            
            <div class="info" style="background: #d4edda; border-color: #28a745;">
                <strong>✅ Confirmation :</strong><br>
                {info['confirmation']}
            </div>
            
            <p style="margin-top: 30px;">
                <a href="/admin" style="padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px;">
                    Retour Admin
                </a>
            </p>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/download_invoice/<invoice_number>')
def download_invoice(invoice_number):
    """Télécharger la facture en JPG"""
    # Récupérer les données du vote
    vote = Vote.query.filter_by(invoice_number=invoice_number).first()
    if not vote:
        return "Facture introuvable", 404
    
    user = User.query.get(vote.user_id)
    candidate = Candidate.query.get(vote.candidate_id)
    
    # Générer le HTML de la facture
    html_content = render_template('vote_success.html',
                                 candidate=candidate,
                                 user=user,
                                 votes_cast=vote.votes_count,
                                 invoice_number=vote.invoice_number,
                                 amount_paid=vote.amount_paid,
                                 vote_date=vote.created_at,
                                 for_download=True)
    
    # Créer un dossier temporaire
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialiser html2image
        hti = Html2Image(output_path=tmpdir)
        
        # Générer l'image
        output_file = f"facture_{invoice_number}.jpg"
        hti.screenshot(html_str=html_content, save_as=output_file, size=(800, 1200))
        
        # Envoyer le fichier
        return send_file(
            os.path.join(tmpdir, output_file),
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=f'facture_vote_{invoice_number}.jpg'
        )

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('Mot de passe incorrect', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin_panel():
    # ULTRA-RAPIDE : Utiliser le cache pour les candidats
    candidates = get_cached_candidates()
    
    # OPTIMISÉ : 1 seule requête pour tous les montants au lieu de N requêtes
    candidate_money_results = db.session.query(
        Vote.candidate_id,
        db.func.sum(Vote.amount_paid).label('total')
    ).group_by(Vote.candidate_id).all()
    
    candidate_money = {result.candidate_id: result.total or 0 for result in candidate_money_results}
    
    # Cache du statut de vote
    voting_status = get_cached_voting_status()
    is_voting_open = voting_status.is_open if voting_status else True
    
    today = get_lubumbashi_date()
    
    # OPTIMISÉ : 1 seule requête pour les votes d'aujourd'hui
    votes_today = Vote.query.filter(db.func.date(Vote.created_at) == today).count()
    
    visit_today = SiteVisit.query.filter_by(visit_date=today).first()
    visitors_today = visit_today.visit_count if visit_today else 0
    
    # OPTIMISÉ : 1 seule requête pour les 7 derniers jours
    seven_days_ago = today - timedelta(days=6)
    votes_by_day = db.session.query(
        db.func.date(Vote.created_at).label('day'),
        db.func.count(Vote.id).label('votes')
    ).filter(
        db.func.date(Vote.created_at) >= seven_days_ago
    ).group_by(db.func.date(Vote.created_at)).all()
    
    votes_dict = {str(v.day): v.votes for v in votes_by_day}
    
    last_7_days = []
    for i in range(7):
        day = today - timedelta(days=i)
        day_str = str(day)
        votes = votes_dict.get(day_str, 0)
        last_7_days.append({'date': day.strftime('%d/%m'), 'votes': votes})
    
    # OPTIMISÉ : Limiter à 100 utilisateurs récents au lieu de TOUS
    all_users = User.query.order_by(User.created_at.desc()).limit(100).all()
    
    # Récupérer la date sélectionnée (par défaut aujourd'hui)
    selected_date_str = request.args.get('date', None)
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except:
            selected_date = today
    else:
        selected_date = today
    
    # Liste des votes pour la date sélectionnée avec détails complets
    selected_votes = db.session.query(Vote, User, Candidate).join(
        User, Vote.user_id == User.id
    ).join(
        Candidate, Vote.candidate_id == Candidate.id
    ).filter(
        db.func.date(Vote.created_at) == selected_date
    ).order_by(Vote.created_at.desc()).all()
    
    # Liste de toutes les dates avec des votes (pour le sélecteur)
    all_vote_dates = db.session.query(
        db.func.date(Vote.created_at).label('vote_date'),
        db.func.count(Vote.id).label('count')
    ).group_by(db.func.date(Vote.created_at)).order_by(db.func.date(Vote.created_at).desc()).all()
    
    team_members = TeamMember.query.order_by(TeamMember.order).all()
    partners = Partner.query.order_by(Partner.order).all()
    categories = Category.query.order_by(Category.order).all()
    
    return render_template('admin.html',
                         candidates=candidates,
                         candidate_money=candidate_money,
                         is_voting_open=is_voting_open,
                         voting_status=voting_status,
                         votes_today=votes_today,
                         visitors_today=visitors_today,
                         last_7_days=reversed(last_7_days),
                         all_users=all_users,
                         today_votes=selected_votes,
                         selected_date=selected_date,
                         all_vote_dates=all_vote_dates,
                         team_members=team_members,
                         partners=partners,
                         categories=categories)

@app.route('/admin/add_candidate', methods=['POST'])
@admin_required
def add_candidate():
    name = request.form.get('name')
    number = int(request.form.get('number'))
    category_id = request.form.get('category_id')
    
    existing = Candidate.query.filter_by(number=number).first()
    if existing:
        flash('Ce numéro existe déjà', 'error')
        return redirect(url_for('admin_panel'))
    
    candidate = Candidate(name=name, number=number)
    
    if category_id:
        candidate.category_id = int(category_id)
    
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            candidate.photo_data = file.read()
            candidate.photo_filename = secure_filename(file.filename)
    
    db.session.add(candidate)
    db.session.commit()
    
    flash('Candidat ajouté avec succès', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_candidate/<int:candidate_id>', methods=['POST'])
@admin_required
def update_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    
    if 'name' in request.form:
        candidate.name = request.form.get('name')
    
    if 'category_id' in request.form and request.form.get('category_id'):
        candidate.category_id = int(request.form.get('category_id'))
    
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            candidate.photo_data = file.read()
            candidate.photo_filename = secure_filename(file.filename)
    
    db.session.commit()
    
    flash('Candidat mis à jour', 'success')
    return redirect(url_for('admin_panel'))

def calculate_price_for_votes(votes_count):
    """
    Calcule le prix exact pour un nombre de votes donné
    basé sur les packages disponibles.
    """
    if votes_count <= 0:
        return 0
    
    # Mapping exact des votes vers les prix selon les packages
    vote_to_price = {
        5: 2500,        # STANDARD
        12: 5000,       # BASIC
        26: 10000,      # CLASSIC
        54: 20000,      # SPÉCIAL
        310: 115000,    # PREMIUM
        625: 230000,    # VIP
        1252: 560000,   # BOUQUET DIAMANT
        2510: 1000000   # BOUQUET OR
    }
    
    # Chercher le package exact qui correspond au nombre de votes
    if votes_count in vote_to_price:
        return vote_to_price[votes_count]
    
    # Si le nombre de votes ne correspond pas exactement à un package,
    # calculer avec le prix par vote du package STANDARD (le plus simple)
    # 2500 FC / 5 votes = 500 FC par vote
    price_per_vote = 500
    return votes_count * price_per_vote

@app.route('/admin/adjust_votes/<int:candidate_id>', methods=['POST'])
@admin_required
def adjust_votes(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    adjustment = int(request.form.get('adjustment', 0))
    
    # Si on ajoute des votes (ajustement positif), créer un enregistrement Vote
    if adjustment > 0:
        # Calculer le prix pour ces votes
        amount = calculate_price_for_votes(adjustment)
        
        # Créer un utilisateur admin fictif si nécessaire (pour les votes manuels)
        admin_user = User.query.filter_by(phone='ADMIN_MANUAL').first()
        if not admin_user:
            admin_user = User(full_name='Admin Manual', phone='ADMIN_MANUAL')
            db.session.add(admin_user)
            db.session.flush()  # Pour obtenir l'ID
        
        # Créer l'enregistrement Vote avec le montant calculé
        vote_record = Vote(
            user_id=admin_user.id,
            candidate_id=candidate_id,
            votes_count=adjustment,
            amount_paid=amount,
            invoice_number=None  # Pas de facture pour les votes manuels
        )
        db.session.add(vote_record)
        
        # Enregistrer les statistiques journalières
        today = get_lubumbashi_date()
        daily_stat = DailyVoteStatistics.query.filter_by(date=today).first()
        if not daily_stat:
            daily_stat = DailyVoteStatistics(date=today, total_votes=0)
            db.session.add(daily_stat)
        daily_stat.total_votes += adjustment
    
    candidate.vote_count = max(0, candidate.vote_count + adjustment)
    db.session.commit()
    
    # Invalider le cache des candidats pour forcer le rechargement
    global _candidates_cache, _candidates_cache_time
    _candidates_cache = None
    _candidates_cache_time = None
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/eliminate_candidate/<int:candidate_id>', methods=['POST'])
@admin_required
def eliminate_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    candidate.is_eliminated = not candidate.is_eliminated
    db.session.commit()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_candidate/<int:candidate_id>', methods=['POST'])
@admin_required
def delete_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    
    # Supprimer tous les votes associés
    Vote.query.filter_by(candidate_id=candidate_id).delete()
    
    # Supprimer toutes les transactions associées
    Transaction.query.filter_by(candidate_id=candidate_id).delete()
    
    # Supprimer le candidat
    db.session.delete(candidate)
    db.session.commit()
    
    flash(f'Candidat {candidate.name} et tous ses votes supprimés', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_all_candidates', methods=['POST'])
@admin_required
def delete_all_candidates():
    # Supprimer tous les votes
    Vote.query.delete()
    
    # Supprimer toutes les transactions
    Transaction.query.delete()
    
    # Supprimer tous les candidats
    Candidate.query.delete()
    
    db.session.commit()
    
    flash('Tous les candidats et tous les votes ont été supprimés', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_all_users', methods=['POST'])
@admin_required
def delete_all_users():
    # Supprimer tous les votes (car ils sont liés aux utilisateurs)
    Vote.query.delete()
    
    # Supprimer toutes les transactions (car elles sont liées aux utilisateurs)
    Transaction.query.delete()
    
    # Supprimer tous les utilisateurs
    User.query.delete()
    
    db.session.commit()
    
    flash('Tous les utilisateurs ont été supprimés (votes et transactions inclus)', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_voting', methods=['POST'])
@admin_required
def toggle_voting():
    voting_status = VotingStatus.query.first()
    if not voting_status:
        voting_status = VotingStatus(is_open=False)
        db.session.add(voting_status)
    else:
        voting_status.is_open = not voting_status.is_open
    
    db.session.commit()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_whatsapp', methods=['POST'])
@admin_required
def toggle_whatsapp():
    whatsapp_status = WhatsAppStatus.query.first()
    if not whatsapp_status:
        whatsapp_status = WhatsAppStatus(is_active=False)
        db.session.add(whatsapp_status)
    else:
        whatsapp_status.is_active = not whatsapp_status.is_active
    
    db.session.commit()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_christmas_hat', methods=['POST'])
@admin_required
def toggle_christmas_hat():
    christmas_hat_status = ChristmasHatStatus.query.first()
    if not christmas_hat_status:
        christmas_hat_status = ChristmasHatStatus(is_active=False)
        db.session.add(christmas_hat_status)
    else:
        christmas_hat_status.is_active = not christmas_hat_status.is_active
    
    db.session.commit()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/sync_laureates', methods=['POST'])
@admin_required
def sync_laureates():
    """Synchroniser les lauréats - calculer les 3 meilleurs de chaque catégorie"""
    try:
        Laureate.query.delete()
        categories = Category.query.all()
        
        for category in categories:
            top_candidates = Candidate.query.filter_by(
                category_id=category.id,
                is_eliminated=False
            ).filter(Candidate.vote_count > 0).order_by(Candidate.vote_count.desc()).limit(3).all()
            
            for pos, candidate in enumerate(top_candidates, 1):
                laureate = Laureate(
                    category_id=category.id,
                    candidate_id=candidate.id,
                    vote_count=candidate.vote_count,
                    position=pos,
                    synced_at=get_lubumbashi_time()
                )
                db.session.add(laureate)
        
        db.session.commit()
        flash('Lauréats synchronisés avec succès! (Top 3 par catégorie)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur: {str(e)}', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_laureate', methods=['POST'])
@admin_required
def add_laureate():
    """Ajouter manuellement un candidat comme lauréat"""
    try:
        candidate_id = request.form.get('candidate_id', type=int)
        pos = request.form.get('rank', type=int, default=1)
        
        candidate = Candidate.query.get(candidate_id)
        if not candidate:
            flash('Candidat non trouvé', 'error')
            return redirect(url_for('admin_panel'))
        
        existing = Laureate.query.filter_by(category_id=candidate.category_id, position=pos).first()
        if existing:
            db.session.delete(existing)
        
        laureate = Laureate(
            category_id=candidate.category_id,
            candidate_id=candidate.id,
            vote_count=candidate.vote_count,
            position=pos,
            synced_at=get_lubumbashi_time()
        )
        db.session.add(laureate)
        db.session.commit()
        
        rank_text = ["", "1er", "2ème", "3ème"][pos] if pos <= 3 else f"{pos}ème"
        flash(f'{candidate.name} ajouté comme {rank_text} meilleur dans sa catégorie!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur: {str(e)}', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/clear_laureates', methods=['POST'])
@admin_required
def clear_laureates():
    """Effacer tous les lauréats"""
    try:
        Laureate.query.delete()
        db.session.commit()
        flash('Tous les lauréats ont été effacés!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur: {str(e)}', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_laureates_visibility', methods=['POST'])
@admin_required
def toggle_laureates_visibility():
    """Activer/désactiver la visibilité du bouton Lauréats"""
    visibility = LaureatesVisibility.query.first()
    if not visibility:
        visibility = LaureatesVisibility(is_visible=False)
        db.session.add(visibility)
    else:
        visibility.is_visible = not visibility.is_visible
    
    db.session.commit()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/download_invoice_jpg/<int:vote_id>')
@admin_required
def download_invoice_jpg(vote_id):
    """Génère et télécharge une facture en JPG pour un vote - même modèle que la page de vote"""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    
    # Récupérer le vote avec ses détails
    vote = Vote.query.get_or_404(vote_id)
    user = User.query.get(vote.user_id)
    candidate = Candidate.query.get(vote.candidate_id)
    
    if not user or not candidate:
        flash('Vote non trouvé', 'error')
        return redirect(url_for('admin_panel'))
    
    # Dimensions de l'image (style carte compacte comme la page vote_success)
    width, height = 500, 750
    
    # Créer l'image avec fond noir/gris foncé
    img = Image.new('RGB', (width, height), color='#1a1a1a')
    draw = ImageDraw.Draw(img)
    
    # Couleurs
    gold = '#ffd700'
    white = '#ffffff'
    gray = '#aaaaaa'
    dark_bg = '#000000'
    
    # Dessiner la carte centrale avec coins arrondis (simulé)
    card_margin = 20
    card_x1, card_y1 = card_margin, card_margin
    card_x2, card_y2 = width - card_margin, height - card_margin
    
    # Fond de la carte noir
    draw.rectangle([(card_x1, card_y1), (card_x2, card_y2)], fill=dark_bg, outline=gold, width=2)
    
    # Police par défaut
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_subtitle = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_votes = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_normal = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_large = ImageFont.load_default()
        font_votes = ImageFont.load_default()
    
    y = 50
    center_x = width // 2
    
    # Titre principal
    title = "FACTURE DE VOTE"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, y), title, fill=gold, font=font_title)
    y += 30
    
    subtitle = "WEB IMPACT SHOW"
    bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, y), subtitle, fill=gold, font=font_subtitle)
    y += 40
    
    # Photo du candidat (cercle)
    photo_size = 100
    photo_x = center_x - photo_size // 2
    photo_y = y
    
    # Dessiner le cercle doré pour la photo
    draw.ellipse([(photo_x - 4, photo_y - 4), (photo_x + photo_size + 4, photo_y + photo_size + 4)], outline=gold, width=3)
    
    # Charger et redimensionner la photo du candidat si disponible
    if candidate.photo_data:
        try:
            candidate_img = Image.open(BytesIO(candidate.photo_data))
            candidate_img = candidate_img.convert('RGB')
            candidate_img = candidate_img.resize((photo_size, photo_size), Image.LANCZOS)
            
            # Créer un masque circulaire
            mask = Image.new('L', (photo_size, photo_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([(0, 0), (photo_size, photo_size)], fill=255)
            
            # Appliquer le masque
            img.paste(candidate_img, (photo_x, photo_y), mask)
        except:
            # Si erreur, dessiner un cercle gris
            draw.ellipse([(photo_x, photo_y), (photo_x + photo_size, photo_y + photo_size)], fill='#333333')
    else:
        draw.ellipse([(photo_x, photo_y), (photo_x + photo_size, photo_y + photo_size)], fill='#333333')
    
    y += photo_size + 15
    
    # Nom du candidat
    candidate_name = candidate.name
    bbox = draw.textbbox((0, 0), candidate_name, font=font_subtitle)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, y), candidate_name, fill=gold, font=font_subtitle)
    y += 25
    
    # Message de remerciement
    thanks_msg = "Merci de m'avoir soutenu(e)"
    bbox = draw.textbbox((0, 0), thanks_msg, font=font_small)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, y), thanks_msg, fill=gray, font=font_small)
    y += 30
    
    # Badge numéro de facture
    invoice_text = f"Facture N° {vote.invoice_number or 'N/A'}"
    bbox = draw.textbbox((0, 0), invoice_text, font=font_subtitle)
    text_width = bbox[2] - bbox[0]
    badge_padding = 15
    badge_height = 30
    badge_x1 = center_x - text_width // 2 - badge_padding
    badge_x2 = center_x + text_width // 2 + badge_padding
    badge_y1 = y
    badge_y2 = y + badge_height
    draw.rounded_rectangle([(badge_x1, badge_y1), (badge_x2, badge_y2)], radius=15, fill=gold)
    draw.text((center_x - text_width // 2, y + 5), invoice_text, fill='#000000', font=font_subtitle)
    y += 50
    
    # Zone des détails
    details_margin = 40
    details_x1 = details_margin
    details_x2 = width - details_margin
    details_y1 = y
    details_height = 250
    
    # Fond semi-transparent pour les détails
    draw.rectangle([(details_x1, details_y1), (details_x2, details_y1 + details_height)], fill='#111111', outline=gold, width=1)
    
    y += 15
    detail_left = details_x1 + 15
    detail_right = details_x2 - 15
    
    # Votes attribués
    draw.text((detail_left, y), "⭐ Votes attribués", fill=gray, font=font_small)
    votes_text = str(vote.votes_count)
    bbox = draw.textbbox((0, 0), votes_text, font=font_votes)
    text_width = bbox[2] - bbox[0]
    draw.text((detail_right - text_width, y - 5), votes_text, fill=gold, font=font_votes)
    y += 40
    
    # Ligne de séparation
    draw.line([(detail_left, y), (detail_right, y)], fill='#333333', width=1)
    y += 15
    
    # Montant payé
    draw.text((detail_left, y), "💰 Montant payé", fill=gray, font=font_small)
    amount = vote.amount_paid or 0
    amount_formatted = "{:,}".format(amount).replace(',', ' ') + " FC"
    bbox = draw.textbbox((0, 0), amount_formatted, font=font_subtitle)
    text_width = bbox[2] - bbox[0]
    draw.text((detail_right - text_width, y), amount_formatted, fill=gold, font=font_subtitle)
    y += 35
    
    # Ligne de séparation
    draw.line([(detail_left, y), (detail_right, y)], fill='#333333', width=1)
    y += 15
    
    # Date et heure
    draw.text((detail_left, y), "📅 Date et heure", fill=gray, font=font_small)
    vote_date = convert_to_lubumbashi(vote.created_at) if vote.created_at else datetime.now()
    date_str = vote_date.strftime('%d/%m/%Y à %H:%M')
    bbox = draw.textbbox((0, 0), date_str, font=font_normal)
    text_width = bbox[2] - bbox[0]
    draw.text((detail_right - text_width, y), date_str, fill=gold, font=font_normal)
    y += 35
    
    # Ligne de séparation
    draw.line([(detail_left, y), (detail_right, y)], fill='#333333', width=1)
    y += 15
    
    # Payeur
    draw.text((detail_left, y), "👤 Payeur", fill=gray, font=font_small)
    bbox = draw.textbbox((0, 0), user.full_name, font=font_normal)
    text_width = bbox[2] - bbox[0]
    draw.text((detail_right - text_width, y), user.full_name, fill=gold, font=font_normal)
    y += 35
    
    # Ligne de séparation
    draw.line([(detail_left, y), (detail_right, y)], fill='#333333', width=1)
    y += 15
    
    # Contact
    draw.text((detail_left, y), "📞 Contact", fill=gray, font=font_small)
    bbox = draw.textbbox((0, 0), user.phone, font=font_normal)
    text_width = bbox[2] - bbox[0]
    draw.text((detail_right - text_width, y), user.phone, fill=gold, font=font_normal)
    
    # Footer
    footer = "© 2025 WEB IMPACT SHOW"
    bbox = draw.textbbox((0, 0), footer, font=font_small)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width // 2, height - 50), footer, fill=gray, font=font_small)
    
    # Sauvegarder dans un buffer
    img_buffer = BytesIO()
    img.save(img_buffer, format='JPEG', quality=95)
    img_buffer.seek(0)
    
    # Nom du fichier
    filename = f"facture_vote_{vote.invoice_number or vote_id}.jpg"
    
    return send_file(
        img_buffer,
        mimetype='image/jpeg',
        as_attachment=True,
        download_name=filename
    )

@app.route('/admin/reset_votes', methods=['POST'])
@admin_required
def reset_votes():
    # Réinitialiser tous les votes des candidats
    candidates = Candidate.query.all()
    for candidate in candidates:
        candidate.vote_count = 0
    
    # Supprimer tous les enregistrements de votes
    Vote.query.delete()
    
    # Supprimer toutes les transactions
    Transaction.query.delete()
    
    db.session.commit()
    
    flash('Tous les votes ont été réinitialisés !', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/init_categories', methods=['POST'])
@admin_required
def init_categories():
    """Initialise les 27 catégories dans la base de données"""
    
    # Vérifier si les catégories existent déjà
    existing_count = Category.query.count()
    if existing_count > 0:
        flash(f'Les catégories existent déjà ({existing_count} catégories). Aucune action effectuée.', 'warning')
        return redirect(url_for('admin_panel'))
    
    # Définir les 27 catégories organisées par domaine
    categories_data = [
        # INFLUENCEURS & COMMUNICATION DIGITALE (10 catégories)
        ("Influenceurs Imitateur de voix", "INFLUENCEURS & COMMUNICATION DIGITALE", 1),
        ("Influenceurs Conseils et comédie", "INFLUENCEURS & COMMUNICATION DIGITALE", 2),
        ("Influenceurs Humoristes", "INFLUENCEURS & COMMUNICATION DIGITALE", 3),
        ("Influenceurs Chroniqueurs", "INFLUENCEURS & COMMUNICATION DIGITALE", 4),
        ("Influenceurs Légendaires", "INFLUENCEURS & COMMUNICATION DIGITALE", 5),
        ("Influenceurs Marketing", "INFLUENCEURS & COMMUNICATION DIGITALE", 6),
        ("Influenceurs Mode / Stylistes", "INFLUENCEURS & COMMUNICATION DIGITALE", 7),
        ("Influenceurs Musicaux / DJ digitaux", "INFLUENCEURS & COMMUNICATION DIGITALE", 8),
        ("Influenceurs Chrétiens", "INFLUENCEURS & COMMUNICATION DIGITALE", 9),
        ("Influenceurs Politiques / Sociaux", "INFLUENCEURS & COMMUNICATION DIGITALE", 10),
        
        # REALISATION VISUEL & CINÉMATOGRAPHIQUE (5 catégories)
        ("Réalisateurs Web", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 11),
        ("Réalisateurs Cinéma", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 12),
        ("Vidéastes Créatifs", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 13),
        ("Scénaristes Web", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 14),
        ("Acteurs Cinéma", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 15),
        
        # ARTS VISUELS & DESIGN NUMÉRIQUE (3 catégories)
        ("Photographes Web", "ARTS VISUELS & DESIGN NUMÉRIQUE", 16),
        ("Designers Numériques", "ARTS VISUELS & DESIGN NUMÉRIQUE", 17),
        ("Make-up Artists / Coiffeurs", "ARTS VISUELS & DESIGN NUMÉRIQUE", 18),
        
        # JOURNALISME & ANALYSE DIGITALE (3 catégories)
        ("Journalistes Web / Chroniqueurs", "JOURNALISME & ANALYSE DIGITALE", 19),
        ("Journalistes Culturels", "JOURNALISME & ANALYSE DIGITALE", 20),
        ("Analystes et Vulgarisateurs d'Actualité", "JOURNALISME & ANALYSE DIGITALE", 21),
        
        # ENTREPRENEURIAT & INNOVATION DIGITALE (4 catégories)
        ("Créateurs E-commerce / Dropshipping", "ENTREPRENEURIAT & INNOVATION DIGITALE", 22),
        ("Entrepreneurs Digitaux", "ENTREPRENEURIAT & INNOVATION DIGITALE", 23),
        ("Motivateurs / Coachs de vie", "ENTREPRENEURIAT & INNOVATION DIGITALE", 24),
        ("Créateurs de Citations Inspirantes", "ENTREPRENEURIAT & INNOVATION DIGITALE", 25),
        
        # SPIRITUALITÉ & IMPACT SOCIAL (2 catégories)
        ("Créateurs de Messages Spirituels", "SPIRITUALITÉ & IMPACT SOCIAL", 26),
        ("Chanteurs / Musiciens Indépendants", "SPIRITUALITÉ & IMPACT SOCIAL", 27),
    ]
    
    # Créer toutes les catégories
    for name, group_name, order in categories_data:
        category = Category(
            name=name,
            group_name=group_name,
            order=order
        )
        db.session.add(category)
    
    db.session.commit()
    
    flash(f'✅ {len(categories_data)} catégories ont été initialisées avec succès !', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/stats_history')
@admin_required
def stats_history():
    """Affiche l'historique COMPLET de TOUTES les statistiques (PERMANENT - aucune suppression)"""
    try:
        # Archiver automatiquement les stats d'hier si elles n'existent pas
        archive_daily_statistics()
    except Exception as e:
        print(f"Erreur lors de l'archivage automatique : {e}")
    
    # Récupérer TOUTES les statistiques archivées (AUCUNE LIMITE - PERMANENT)
    archived_stats = DailyVoteStatistics.query.order_by(DailyVoteStatistics.date.desc()).all()
    
    # Calculer les totaux généraux (avec protection contre None)
    total_votes_all_time = sum(stat.total_votes or 0 for stat in archived_stats)
    total_amount_all_time = sum(stat.total_amount_fc or 0 for stat in archived_stats)
    total_transactions_all_time = sum(stat.total_transactions or 0 for stat in archived_stats)
    
    # Ajouter les votes d'aujourd'hui (non encore archivés)
    today = get_lubumbashi_date()
    today_start = datetime.combine(today, datetime.min.time())
    today_start = LUBUMBASHI_TZ.localize(today_start)
    
    today_votes = Vote.query.filter(Vote.created_at >= today_start).all()
    today_total_votes = sum(vote.votes_count or 0 for vote in today_votes)
    today_total_amount = sum(vote.amount_paid or 0 for vote in today_votes)
    today_total_transactions = len(today_votes)
    
    # Formater la date d'aujourd'hui
    today_formatted = today.strftime('%d/%m/%Y')
    
    return render_template('stats_history.html',
                         archived_stats=archived_stats,
                         total_votes_all_time=total_votes_all_time + today_total_votes,
                         total_amount_all_time=total_amount_all_time + today_total_amount,
                         total_transactions_all_time=total_transactions_all_time + today_total_transactions,
                         today_votes=today_total_votes,
                         today_amount=today_total_amount,
                         today_transactions=today_total_transactions,
                         today_date=today_formatted)

@app.route('/admin/archive_stats/<date_str>', methods=['POST'])
@admin_required
def manually_archive_stats(date_str):
    """Permet d'archiver manuellement les stats d'une date spécifique"""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        archive_daily_statistics(target_date)
        flash(f'✅ Statistiques du {date_str} archivées avec succès !', 'success')
    except Exception as e:
        flash(f'❌ Erreur lors de l\'archivage : {str(e)}', 'error')
    
    return redirect(url_for('stats_history'))

@app.route('/admin/archive_all_missing', methods=['POST'])
@admin_required
def archive_all_missing_stats():
    """Archive TOUS les jours manquants depuis le premier vote"""
    try:
        # Trouver le premier vote
        first_vote = Vote.query.order_by(Vote.created_at).first()
        if not first_vote:
            flash('❌ Aucun vote trouvé dans la base de données', 'error')
            return redirect(url_for('admin_panel'))
        
        # Date de début = date du premier vote
        start_date = first_vote.created_at.date()
        # Date de fin = hier
        end_date = get_lubumbashi_date() - timedelta(days=1)
        
        archived_count = 0
        current_date = start_date
        
        while current_date <= end_date:
            existing = DailyVoteStatistics.query.filter_by(date=current_date).first()
            if not existing:
                archive_daily_statistics(current_date)
                archived_count += 1
            current_date += timedelta(days=1)
        
        if archived_count > 0:
            flash(f'✅ {archived_count} jour(s) archivé(s) avec succès !', 'success')
        else:
            flash('✅ Tous les jours sont déjà archivés !', 'success')
            
    except Exception as e:
        flash(f'❌ Erreur : {str(e)}', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_votes_visibility', methods=['POST'])
@admin_required
def toggle_votes_visibility():
    voting_status = VotingStatus.query.first()
    if not voting_status:
        voting_status = VotingStatus(is_open=True, votes_hidden=False)
        db.session.add(voting_status)
    
    # Basculer la visibilité de la zone de votes
    voting_status.votes_hidden = not voting_status.votes_hidden
    
    db.session.commit()
    
    if voting_status.votes_hidden:
        flash('La zone de votes est maintenant masquée sur la page d\'accueil', 'success')
    else:
        flash('La zone de votes est maintenant visible sur la page d\'accueil', 'success')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_team_member', methods=['POST'])
@admin_required
def add_team_member():
    name = request.form.get('name')
    role = request.form.get('role')
    description = request.form.get('description')
    order = int(request.form.get('order', 0))
    
    member = TeamMember(name=name, role=role, description=description, order=order)
    
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            member.photo_data = file.read()
            member.photo_filename = secure_filename(file.filename)
    
    db.session.add(member)
    db.session.commit()
    
    flash('Membre de l\'équipe ajouté avec succès', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_team_member/<int:member_id>', methods=['POST'])
@admin_required
def update_team_member(member_id):
    member = TeamMember.query.get_or_404(member_id)
    
    if 'name' in request.form:
        member.name = request.form.get('name')
    if 'role' in request.form:
        member.role = request.form.get('role')
    if 'description' in request.form:
        member.description = request.form.get('description')
    if 'order' in request.form:
        member.order = int(request.form.get('order'))
    
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            member.photo_data = file.read()
            member.photo_filename = secure_filename(file.filename)
    
    db.session.commit()
    
    flash('Membre de l\'équipe mis à jour', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_team_member/<int:member_id>', methods=['POST'])
@admin_required
def delete_team_member(member_id):
    member = TeamMember.query.get_or_404(member_id)
    db.session.delete(member)
    db.session.commit()
    
    flash('Membre de l\'équipe supprimé', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_partner', methods=['POST'])
@admin_required
def add_partner():
    name = request.form.get('name')
    website_url = request.form.get('website_url', '')
    order = int(request.form.get('order', 0))
    
    partner = Partner(name=name, website_url=website_url, order=order)
    
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename:
            partner.logo_data = file.read()
            partner.logo_filename = secure_filename(file.filename)
    
    db.session.add(partner)
    db.session.commit()
    
    flash('Partenaire ajouté avec succès', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_partner/<int:partner_id>', methods=['POST'])
@admin_required
def update_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    
    if 'name' in request.form:
        partner.name = request.form.get('name')
    if 'website_url' in request.form:
        partner.website_url = request.form.get('website_url')
    if 'order' in request.form:
        partner.order = int(request.form.get('order'))
    
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename:
            partner.logo_data = file.read()
            partner.logo_filename = secure_filename(file.filename)
    
    db.session.commit()
    
    flash('Partenaire mis à jour', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_partner/<int:partner_id>', methods=['POST'])
@admin_required
def toggle_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    partner.is_active = not partner.is_active
    db.session.commit()
    
    status = 'activé' if partner.is_active else 'désactivé'
    flash(f'Partenaire {status}', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_partner/<int:partner_id>', methods=['POST'])
@admin_required
def delete_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    db.session.delete(partner)
    db.session.commit()
    
    flash('Partenaire supprimé', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/get_all_votes')
def get_all_votes():
    """Récupérer TOUS les votes en UNE seule requête - ULTRA RAPIDE"""
    try:
        cached_candidates = get_cached_candidates()
        votes_data = {c.id: c.vote_count for c in cached_candidates}
        
        response = jsonify(votes_data)
        # Cache HTTP de 3 secondes
        response.cache_control.max_age = 3
        response.cache_control.public = True
        return response
    except Exception as e:
        print(f"ERREUR get_all_votes: {str(e)}")
        return jsonify({}), 200

@app.route('/get_vote_count/<int:candidate_id>')
def get_vote_count(candidate_id):
    """Route de compatibilité - utilise le cache"""
    try:
        cached_candidates = get_cached_candidates()
        candidate = next((c for c in cached_candidates if c.id == candidate_id), None)
        
        if not candidate:
            candidate = Candidate.query.get_or_404(candidate_id)
        
        response = jsonify({'vote_count': candidate.vote_count})
        response.cache_control.max_age = 3
        response.cache_control.public = True
        return response
    except Exception as e:
        print(f"ERREUR get_vote_count: {str(e)}")
        return jsonify({'vote_count': 0}), 200

@app.route('/candidate_photo/<int:candidate_id>')
def get_candidate_photo(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    
    if not candidate.photo_data:
        return redirect('https://via.placeholder.com/300?text=N°' + str(candidate.number))
    
    from io import BytesIO
    from PIL import Image
    
    # OPTIMISATION CONNEXION LENTE : Réduire la taille de l'image
    try:
        img = Image.open(BytesIO(candidate.photo_data))
        
        # Redimensionner à max 400x600 pour connexions lentes
        max_size = (400, 600)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convertir en JPEG avec qualité réduite (70% au lieu de 100%)
        output = BytesIO()
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img.save(output, format='JPEG', quality=70, optimize=True)
        output.seek(0)
        
        response = send_file(
            output,
            mimetype='image/jpeg',
            as_attachment=False,
            download_name=candidate.photo_filename or f'candidate_{candidate.number}.jpg'
        )
    except Exception as e:
        print(f"ERREUR optimisation image: {e}")
        # Fallback : servir l'image originale
        response = send_file(
            BytesIO(candidate.photo_data),
            mimetype='image/jpeg',
            as_attachment=False,
            download_name=candidate.photo_filename or f'candidate_{candidate.number}.jpg'
        )
    
    # Cache HTTP de 1 heure pour les photos
    response.cache_control.max_age = 3600
    response.cache_control.public = True
    return response

@app.route('/team_photo/<int:member_id>')
def get_team_photo(member_id):
    member = TeamMember.query.get_or_404(member_id)
    
    if not member.photo_data:
        return redirect('https://via.placeholder.com/300?text=' + member.name[0])
    
    from io import BytesIO
    response = send_file(
        BytesIO(member.photo_data),
        mimetype='image/jpeg',
        as_attachment=False,
        download_name=member.photo_filename or f'team_{member.id}.jpg'
    )
    # Cache HTTP de 1 heure
    response.cache_control.max_age = 3600
    response.cache_control.public = True
    return response

@app.route('/partner_logo/<int:partner_id>')
def get_partner_logo(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    
    if not partner.logo_data:
        return redirect('https://via.placeholder.com/200x100?text=' + partner.name[:3])
    
    from io import BytesIO
    from PIL import Image
    
    # OPTIMISATION CONNEXION LENTE : Réduire la taille des logos
    try:
        img = Image.open(BytesIO(partner.logo_data))
        
        # Redimensionner à max 200x100 pour connexions lentes
        max_size = (200, 100)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convertir en PNG optimisé
        output = BytesIO()
        img.save(output, format='PNG', optimize=True)
        output.seek(0)
        
        response = send_file(
            output,
            mimetype='image/png',
            as_attachment=False,
            download_name=partner.logo_filename or f'partner_{partner.id}.png'
        )
    except Exception as e:
        print(f"ERREUR optimisation logo: {e}")
        response = send_file(
            BytesIO(partner.logo_data),
            mimetype='image/png',
            as_attachment=False,
            download_name=partner.logo_filename or f'partner_{partner.id}.png'
        )
    
    # Cache HTTP de 1 heure
    response.cache_control.max_age = 3600
    response.cache_control.public = True
    return response

@app.route('/api/chariow/webhook', methods=['POST'])
def chariow_webhook():
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    
    transaction_token = data.get('transaction_token')
    payment_status = data.get('status')
    signature = data.get('signature')
    
    if not all([transaction_token, payment_status]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    transaction = Transaction.query.filter_by(session_token=transaction_token).first()
    
    if not transaction:
        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
    
    if transaction.votes_remaining > 0:
        return jsonify({'success': False, 'message': 'Transaction already processed'}), 400
    
    if payment_status == 'success':
        transaction.votes_remaining = transaction.votes_purchased
        db.session.commit()
        return jsonify({'success': True, 'message': 'Payment confirmed and votes activated'})
    
    return jsonify({'success': False, 'message': 'Payment not successful'}), 400

@app.route('/api/dashboard_stats')
def dashboard_stats():
    total_participants = User.query.count()
    total_votes = db.session.query(db.func.sum(Candidate.vote_count)).scalar() or 0
    top_candidate = Candidate.query.filter_by(is_eliminated=False).order_by(Candidate.vote_count.desc()).first()
    
    return jsonify({
        'total_participants': total_participants,
        'total_votes': total_votes,
        'top_candidate': {
            'id': top_candidate.id,
            'name': top_candidate.name,
            'vote_count': top_candidate.vote_count
        } if top_candidate else None
    })

@app.route('/admin/download_report')
@admin_required
def download_report():
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           rightMargin=30, leftMargin=30,
                           topMargin=30, bottomMargin=18)
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1e3c72'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=12,
        spaceBefore=12,
        fontName='Helvetica-Bold'
    )
    
    title = Paragraph("WEB IMPACT SHOW - Rapport des Votes", title_style)
    elements.append(title)
    
    subtitle = Paragraph(f"Généré le {get_lubumbashi_time().strftime('%d/%m/%Y à %H:%M')}", styles['Normal'])
    elements.append(subtitle)
    elements.append(Spacer(1, 20))
    
    total_votes = db.session.query(db.func.sum(Candidate.vote_count)).scalar() or 0
    total_users = User.query.count()
    total_candidates = Candidate.query.count()
    
    stats_heading = Paragraph("📊 STATISTIQUES GÉNÉRALES", heading_style)
    elements.append(stats_heading)
    
    stats_data = [
        ['Total des candidats', str(total_candidates)],
        ['Total des participants', str(total_users)],
        ['Total des votes', str(total_votes)]
    ]
    
    stats_table = Table(stats_data, colWidths=[4*inch, 2*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey)
    ]))
    
    elements.append(stats_table)
    elements.append(Spacer(1, 20))
    
    candidates_heading = Paragraph("🏆 CLASSEMENT DES CANDIDATS", heading_style)
    elements.append(candidates_heading)
    
    candidates = Candidate.query.order_by(Candidate.vote_count.desc()).all()
    
    candidate_data = [['#', 'N°', 'Nom', 'Votes', 'Argent Généré', 'Statut']]
    
    for idx, candidate in enumerate(candidates, 1):
        # Calculer le total d'argent généré par ce candidat
        total_money = db.session.query(db.func.sum(Vote.amount_paid)).filter(
            Vote.candidate_id == candidate.id
        ).scalar() or 0
        
        status = "❌ Éliminé" if candidate.is_eliminated else "✅ Actif"
        candidate_data.append([
            str(idx),
            str(candidate.number),
            candidate.name,
            str(candidate.vote_count),
            f"{total_money:,} FC".replace(',', ' '),
            status
        ])
    
    candidate_table = Table(candidate_data, colWidths=[0.4*inch, 0.4*inch, 2.2*inch, 0.8*inch, 1.3*inch, 1*inch])
    candidate_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    
    elements.append(candidate_table)
    elements.append(PageBreak())
    
    users_heading = Paragraph("👥 LISTE DES PARTICIPANTS", heading_style)
    elements.append(users_heading)
    
    users = User.query.order_by(User.created_at.desc()).all()
    
    user_data = [['ID', 'Nom Complet', 'Téléphone', 'Date d\'inscription']]
    
    for user in users:
        user_data.append([
            str(user.id),
            user.full_name,
            user.phone,
            convert_to_lubumbashi(user.created_at).strftime('%d/%m/%Y %H:%M')
        ])
    
    user_table = Table(user_data, colWidths=[0.5*inch, 2.5*inch, 1.5*inch, 2*inch])
    user_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    
    elements.append(user_table)
    elements.append(PageBreak())
    
    today = get_lubumbashi_date()
    votes_heading = Paragraph(f"🗳️ VOTES DU JOUR ({today.strftime('%d/%m/%Y')})", heading_style)
    elements.append(votes_heading)
    
    today_votes = Vote.query.filter(
        db.func.date(Vote.created_at) == today
    ).order_by(Vote.created_at.desc()).all()
    
    vote_data = [['Heure', 'N° Facture', 'Utilisateur', 'Téléphone', 'Candidat', 'Votes', 'Total Argent Candidat', 'Montant']]
    
    for vote in today_votes:
        user = User.query.get(vote.user_id)
        candidate = Candidate.query.get(vote.candidate_id)
        
        # Calculer le total d'argent généré par ce candidat
        total_money = db.session.query(db.func.sum(Vote.amount_paid)).filter(
            Vote.candidate_id == candidate.id
        ).scalar() or 0 if candidate else 0
        
        vote_data.append([
            convert_to_lubumbashi(vote.created_at).strftime('%H:%M:%S'),
            vote.invoice_number or 'N/A',
            user.full_name if user else 'N/A',
            user.phone if user else 'N/A',
            f"N°{candidate.number} - {candidate.name}" if candidate else 'N/A',
            str(vote.votes_count),
            f"{total_money:,} FC".replace(',', ' '),
            f"{vote.amount_paid or 0:,} FC".replace(',', ' ')
        ])
    
    if len(vote_data) > 1:
        vote_table = Table(vote_data, colWidths=[0.6*inch, 0.7*inch, 1.3*inch, 1*inch, 1.5*inch, 0.5*inch, 1*inch, 0.9*inch])
        vote_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
        ]))
        elements.append(vote_table)
    else:
        no_votes = Paragraph("Aucun vote enregistré aujourd'hui.", styles['Normal'])
        elements.append(no_votes)
    
    doc.build(elements)
    
    buffer.seek(0)
    
    filename = f"rapport_votes_{get_lubumbashi_time().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )

def initialize_categories():
    """Initialise les 27 catégories de candidats"""
    categories_data = [
        # INFLUENCEURS & COMMUNICATION DIGITALE
        ("Influenceurs Imitateur de voix", "INFLUENCEURS & COMMUNICATION DIGITALE", 1),
        ("Influenceurs Conseils et comédie", "INFLUENCEURS & COMMUNICATION DIGITALE", 2),
        ("Influenceurs Humoristes", "INFLUENCEURS & COMMUNICATION DIGITALE", 3),
        ("Influenceurs Chroniqueurs", "INFLUENCEURS & COMMUNICATION DIGITALE", 4),
        ("Influenceurs Légendaires", "INFLUENCEURS & COMMUNICATION DIGITALE", 5),
        ("Influenceurs Marketing", "INFLUENCEURS & COMMUNICATION DIGITALE", 6),
        ("Influenceurs Mode / Stylistes", "INFLUENCEURS & COMMUNICATION DIGITALE", 7),
        ("Influenceurs Musicaux / DJ digitaux", "INFLUENCEURS & COMMUNICATION DIGITALE", 8),
        ("Influenceurs Chrétiens", "INFLUENCEURS & COMMUNICATION DIGITALE", 9),
        ("Influenceurs Politiques / Sociaux", "INFLUENCEURS & COMMUNICATION DIGITALE", 10),
        
        # REALISATION VISUEL & CINÉMATOGRAPHIQUE
        ("Réalisateurs Web", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 11),
        ("Réalisateurs Cinéma", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 12),
        ("Vidéastes Créatifs", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 13),
        ("Scénaristes Web", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 14),
        ("Acteurs Cinéma", "REALISATION VISUEL & CINÉMATOGRAPHIQUE", 15),
        
        # ARTS VISUELS & DESIGN NUMÉRIQUE
        ("Photographes Web", "ARTS VISUELS & DESIGN NUMÉRIQUE", 16),
        ("Designers Numériques", "ARTS VISUELS & DESIGN NUMÉRIQUE", 17),
        ("Make-up Artists / Coiffeurs", "ARTS VISUELS & DESIGN NUMÉRIQUE", 18),
        
        # JOURNALISME & ANALYSE DIGITALE
        ("Journalistes Web / Chroniqueurs", "JOURNALISME & ANALYSE DIGITALE", 19),
        ("Journalistes Culturels", "JOURNALISME & ANALYSE DIGITALE", 20),
        ("Analystes et Vulgarisateurs d'Actualité", "JOURNALISME & ANALYSE DIGITALE", 21),
        
        # ENTREPRENEURIAT & INNOVATION DIGITALE
        ("Créateurs E-commerce / Dropshipping", "ENTREPRENEURIAT & INNOVATION DIGITALE", 22),
        ("Entrepreneurs Digitaux", "ENTREPRENEURIAT & INNOVATION DIGITALE", 23),
        ("Motivateurs / Coachs de vie", "ENTREPRENEURIAT & INNOVATION DIGITALE", 24),
        ("Créateurs de Citations Inspirantes", "ENTREPRENEURIAT & INNOVATION DIGITALE", 25),
        
        # SPIRITUALITÉ & IMPACT SOCIAL
        ("Créateurs de Messages Spirituels", "SPIRITUALITÉ & IMPACT SOCIAL", 26),
        ("Chanteurs / Musiciens Indépendants", "SPIRITUALITÉ & IMPACT SOCIAL", 27),
    ]
    
    for name, group, order in categories_data:
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            category = Category(name=name, group_name=group, order=order)
            db.session.add(category)
    
    db.session.commit()

@app.route('/test_voice')
def test_voice():
    """Page de test pour la synthèse vocale"""
    return '''
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Test Synthèse Vocale</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                padding: 20px;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                text-align: center;
                max-width: 600px;
            }
            h1 {
                color: #667eea;
                margin-bottom: 20px;
            }
            .btn {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 15px 40px;
                font-size: 18px;
                border-radius: 50px;
                cursor: pointer;
                margin: 10px;
                transition: transform 0.2s;
            }
            .btn:hover {
                transform: scale(1.05);
            }
            .console {
                background: #1e1e1e;
                color: #0f0;
                padding: 20px;
                border-radius: 10px;
                margin-top: 20px;
                text-align: left;
                font-family: monospace;
                font-size: 14px;
                max-height: 300px;
                overflow-y: auto;
            }
            .log-line {
                margin: 5px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔊 Test de Synthèse Vocale</h1>
            <p>Cliquez sur le bouton pour tester la voix française !</p>
            
            <button class="btn" onclick="testVoice()">🎙️ TESTER LA VOIX</button>
            <button class="btn" onclick="clearConsole()">🗑️ Effacer Console</button>
            
            <div class="console" id="console">
                <div class="log-line">📋 Console de débogage (cliquez "Tester la voix" pour commencer)</div>
            </div>
        </div>

        <script>
            function log(message, emoji = '📌') {
                const console = document.getElementById('console');
                const line = document.createElement('div');
                line.className = 'log-line';
                const time = new Date().toLocaleTimeString('fr-FR');
                line.textContent = `[${time}] ${emoji} ${message}`;
                console.appendChild(line);
                console.scrollTop = console.scrollHeight;
            }

            function clearConsole() {
                document.getElementById('console').innerHTML = '<div class="log-line">📋 Console effacée</div>';
            }

            function testVoice() {
                log('Démarrage du test de synthèse vocale...', '🎬');
                
                if (!('speechSynthesis' in window)) {
                    log('ERREUR: La synthèse vocale n\'est pas supportée par ce navigateur', '❌');
                    alert('Votre navigateur ne supporte pas la synthèse vocale. Essayez Chrome, Edge ou Safari.');
                    return;
                }

                log('✅ speechSynthesis détecté dans le navigateur', '✅');

                // Annuler toute synthèse en cours
                window.speechSynthesis.cancel();
                log('Annulation de toute synthèse en cours', '🔄');

                // Créer le message de test
                const candidateNumber = 7;
                const message = `MERCI D'AVOIR VOTÉ POUR LE NUMÉRO ${candidateNumber}. Merci de télécharger votre reçu.`;
                
                log(`Message: "${message}"`, '📝');

                // Fonction pour lancer la voix
                const speak = () => {
                    const utterance = new SpeechSynthesisUtterance(message);
                    utterance.lang = 'fr-FR';
                    utterance.rate = 0.9;
                    utterance.pitch = 1;
                    utterance.volume = 1;
                    
                    log(`Configuration: lang=fr-FR, rate=0.9, pitch=1, volume=1`, '⚙️');

                    // Événements
                    utterance.onstart = () => log('🎙️ VOIX DÉMARRÉE !', '✅');
                    utterance.onend = () => log('VOIX TERMINÉE !', '✅');
                    utterance.onerror = (e) => log(`ERREUR: ${e.error} - ${e.message}`, '❌');

                    // Trouver les voix
                    const voices = window.speechSynthesis.getVoices();
                    log(`${voices.length} voix disponibles`, '🎙️');
                    
                    // Lister les voix françaises
                    const frenchVoices = voices.filter(voice => voice.lang.startsWith('fr'));
                    if (frenchVoices.length > 0) {
                        log(`${frenchVoices.length} voix françaises trouvées:`, '🇫🇷');
                        frenchVoices.forEach((voice, i) => {
                            log(`  ${i+1}. ${voice.name} (${voice.lang})`, '  ');
                        });
                        utterance.voice = frenchVoices[0];
                        log(`Utilisation de: ${frenchVoices[0].name}`, '🎯');
                    } else {
                        log('Aucune voix française, utilisation de la voix par défaut', '⚠️');
                    }

                    // Lancer la synthèse
                    window.speechSynthesis.speak(utterance);
                    log('speechSynthesis.speak() appelé', '🚀');
                };

                // Charger et lancer
                const voices = window.speechSynthesis.getVoices();
                if (voices.length > 0) {
                    log('Voix déjà chargées, lancement immédiat', '⚡');
                    speak();
                } else {
                    log('Attente du chargement des voix...', '⏳');
                    window.speechSynthesis.onvoiceschanged = () => {
                        log('Voix chargées !', '✅');
                        speak();
                    };
                    // Fallback
                    setTimeout(() => {
                        log('Tentative fallback après 500ms', '🔄');
                        speak();
                    }, 500);
                }
            }

            // Test automatique au chargement de la page
            window.addEventListener('load', () => {
                log('Page chargée, prêt pour le test', '✅');
                log('Cliquez sur "TESTER LA VOIX" pour commencer', '👆');
            });
        </script>
    </body>
    </html>
    '''

# Initialiser automatiquement la base de données au démarrage (dev ET production)
with app.app_context():
    db.create_all()
    
    if not VotingStatus.query.first():
        voting_status = VotingStatus(is_open=True)
        db.session.add(voting_status)
        db.session.commit()
    
    if not WhatsAppStatus.query.first():
        whatsapp_status = WhatsAppStatus(is_active=True)
        db.session.add(whatsapp_status)
        db.session.commit()
    
    if not ChristmasHatStatus.query.first():
        christmas_hat_status = ChristmasHatStatus(is_active=True)
        db.session.add(christmas_hat_status)
        db.session.commit()
    
    # Initialiser les catégories
    initialize_categories()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
