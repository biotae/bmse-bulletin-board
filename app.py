import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

import jwt
import markupsafe
import cloudinary
import cloudinary.uploader
from flask import (
    Flask, render_template, redirect, url_for,
    flash, request, abort, send_from_directory, jsonify
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.utils import secure_filename

from config import Config
from models import db, User, Post, Attachment, Comment

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config.from_object(Config)

# Configure Cloudinary if credentials are set
if app.config.get('CLOUDINARY_CLOUD_NAME'):
    cloudinary.config(
        cloud_name=app.config['CLOUDINARY_CLOUD_NAME'],
        api_key=app.config['CLOUDINARY_API_KEY'],
        api_secret=app.config['CLOUDINARY_API_SECRET'],
        secure=True,
    )

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요한 페이지입니다.'
login_manager.login_message_category = 'warning'


# ---------------------------------------------------------------------------
# Template filters and context processors
# ---------------------------------------------------------------------------

@app.template_filter('nl2br')
def nl2br_filter(value):
    """Convert newlines to <br> tags, escaping HTML first."""
    if value is None:
        return ''
    escaped = markupsafe.escape(value)
    return markupsafe.Markup(escaped.replace('\n', markupsafe.Markup('<br>')))


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Helpers / decorators
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )


def save_uploaded_file(file_storage):
    """Upload a file; returns (stored_id, original_filename, size, file_url) or None."""
    if not file_storage or file_storage.filename == '':
        return None
    if not allowed_file(file_storage.filename):
        return None
    original_name = secure_filename(file_storage.filename)

    if app.config.get('CLOUDINARY_CLOUD_NAME'):
        file_bytes = file_storage.read()
        result = cloudinary.uploader.upload(
            file_bytes,
            resource_type='raw',
            folder='bmse_board',
            use_filename=True,
            unique_filename=True,
        )
        return result['public_id'], original_name, result.get('bytes', len(file_bytes)), result['secure_url']
    else:
        ext = original_name.rsplit('.', 1)[1].lower()
        stored_name = f'{uuid.uuid4().hex}.{ext}'
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        file_storage.save(save_path)
        size = os.path.getsize(save_path)
        return stored_name, original_name, size, None


def delete_uploaded_file(att):
    """Delete a file from Cloudinary or local filesystem."""
    if att.file_url:
        try:
            cloudinary.uploader.destroy(att.filename, resource_type='raw')
        except Exception:
            pass
    else:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], att.filename)
        if os.path.exists(file_path):
            os.remove(file_path)


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

def init_db():
    db.create_all()
    if User.query.count() == 0:
        admin = User(
            username='admin',
            email='admin@bmse.ac.kr',
            role='admin',
            is_active=True,
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('[init] Default admin user created  (admin / admin123)')


with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f'[WARNING] DB init failed: {e}')
        print(f'[WARNING] DATABASE_URL={app.config.get("SQLALCHEMY_DATABASE_URI", "not set")}')

@app.route('/healthz')
def healthz():
    try:
        db.session.execute(db.text('SELECT 1'))
        return 'OK', 200
    except Exception as e:
        return f'DB error: {e}', 500


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('board_list'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
            return render_template('auth/login.html')

        if not user.is_active:
            flash('계정이 아직 활성화되지 않았습니다. 관리자에게 문의하세요.', 'warning')
            return render_template('auth/login.html')

        login_user(user, remember=True)
        flash(f'환영합니다, {user.username}님!', 'success')
        next_page = request.args.get('next')
        return redirect(next_page or url_for('board_list'))

    return render_template('auth/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('board_list'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        error = None
        if not username:
            error = '아이디를 입력해주세요.'
        elif not email:
            error = '이메일을 입력해주세요.'
        elif not password:
            error = '비밀번호를 입력해주세요.'
        elif password != confirm:
            error = '비밀번호가 일치하지 않습니다.'
        elif User.query.filter_by(username=username).first():
            error = '이미 사용 중인 아이디입니다.'
        elif User.query.filter_by(email=email).first():
            error = '이미 사용 중인 이메일입니다.'

        if error:
            flash(error, 'danger')
            return render_template('auth/register.html')

        user = User(username=username, email=email, role='member', is_active=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('회원가입 신청이 완료되었습니다. 관리자 승인 후 로그인하실 수 있습니다.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Board routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return redirect(url_for('board_list'))


@app.route('/board')
@login_required
def board_list():
    page = request.args.get('page', 1, type=int)
    pagination = (
        Post.query
        .order_by(Post.created_at.desc())
        .paginate(page=page, per_page=app.config['POSTS_PER_PAGE'], error_out=False)
    )
    posts = pagination.items
    return render_template('board/list.html', posts=posts, pagination=pagination)


@app.route('/board/new', methods=['GET'])
@login_required
def board_new():
    return render_template('board/create.html')


@app.route('/board', methods=['POST'])
@login_required
def board_create():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if not title:
        flash('제목을 입력해주세요.', 'danger')
        return render_template('board/create.html')
    if not content:
        flash('내용을 입력해주세요.', 'danger')
        return render_template('board/create.html')

    post = Post(title=title, content=content, author_id=current_user.id)
    db.session.add(post)
    db.session.flush()  # get post.id before commit

    files = request.files.getlist('files')
    skipped = 0
    for f in files:
        result = save_uploaded_file(f)
        if result is None:
            if f.filename:
                skipped += 1
            continue
        stored_name, original_name, size, file_url = result
        attachment = Attachment(
            post_id=post.id,
            filename=stored_name,
            original_filename=original_name,
            file_size=size,
            file_url=file_url,
        )
        db.session.add(attachment)

    db.session.commit()

    if skipped:
        flash(f'게시글이 등록되었습니다. (허용되지 않는 파일 {skipped}개는 업로드되지 않았습니다.)', 'warning')
    else:
        flash('게시글이 등록되었습니다.', 'success')
    return redirect(url_for('board_detail', post_id=post.id))


@app.route('/board/<int:post_id>')
@login_required
def board_detail(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)

    post.view_count += 1
    db.session.commit()

    attachments = post.attachments.all()
    comments = post.comments.order_by(Comment.created_at.asc()).all()

    return render_template(
        'board/detail.html',
        post=post,
        attachments=attachments,
        comments=comments,
    )


@app.route('/board/<int:post_id>/edit', methods=['GET'])
@login_required
def board_edit(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    if post.author_id != current_user.id and not current_user.is_admin():
        abort(403)

    attachments = post.attachments.all()
    return render_template('board/edit.html', post=post, attachments=attachments)


@app.route('/board/<int:post_id>/edit', methods=['POST'])
@login_required
def board_update(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    if post.author_id != current_user.id and not current_user.is_admin():
        abort(403)

    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if not title:
        flash('제목을 입력해주세요.', 'danger')
        return redirect(url_for('board_edit', post_id=post_id))
    if not content:
        flash('내용을 입력해주세요.', 'danger')
        return redirect(url_for('board_edit', post_id=post_id))

    post.title = title
    post.content = content
    post.updated_at = datetime.utcnow()

    # Delete individually checked attachments
    delete_ids = request.form.getlist('delete_attachments')
    for att_id in delete_ids:
        att = db.session.get(Attachment, int(att_id))
        if att and att.post_id == post.id:
            delete_uploaded_file(att)
            db.session.delete(att)

    # Add new files
    files = request.files.getlist('files')
    skipped = 0
    for f in files:
        result = save_uploaded_file(f)
        if result is None:
            if f.filename:
                skipped += 1
            continue
        stored_name, original_name, size, file_url = result
        attachment = Attachment(
            post_id=post.id,
            filename=stored_name,
            original_filename=original_name,
            file_size=size,
            file_url=file_url,
        )
        db.session.add(attachment)

    db.session.commit()

    if skipped:
        flash(f'게시글이 수정되었습니다. (허용되지 않는 파일 {skipped}개는 업로드되지 않았습니다.)', 'warning')
    else:
        flash('게시글이 수정되었습니다.', 'success')
    return redirect(url_for('board_detail', post_id=post.id))


@app.route('/board/<int:post_id>/delete', methods=['POST'])
@login_required
def board_delete(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    if post.author_id != current_user.id and not current_user.is_admin():
        abort(403)

    for att in post.attachments.all():
        delete_uploaded_file(att)

    db.session.delete(post)
    db.session.commit()

    flash('게시글이 삭제되었습니다.', 'success')
    return redirect(url_for('board_list'))


# ---------------------------------------------------------------------------
# Comment routes
# ---------------------------------------------------------------------------

@app.route('/board/<int:post_id>/comment', methods=['POST'])
@login_required
def comment_create(post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)

    content = request.form.get('content', '').strip()
    if not content:
        flash('댓글 내용을 입력해주세요.', 'danger')
        return redirect(url_for('board_detail', post_id=post_id))

    comment = Comment(post_id=post_id, author_id=current_user.id, content=content)
    db.session.add(comment)
    db.session.commit()

    flash('댓글이 등록되었습니다.', 'success')
    return redirect(url_for('board_detail', post_id=post_id) + '#comments')


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def comment_delete(comment_id):
    comment = db.session.get(Comment, comment_id)
    if comment is None:
        abort(404)
    if comment.author_id != current_user.id and not current_user.is_admin():
        abort(403)

    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()

    flash('댓글이 삭제되었습니다.', 'success')
    return redirect(url_for('board_detail', post_id=post_id) + '#comments')


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    att = Attachment.query.filter_by(filename=filename).first_or_404()
    if att.file_url:
        return redirect(att.file_url)
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        att.filename,
        as_attachment=True,
        download_name=att.original_filename,
    )


# ---------------------------------------------------------------------------
# Profile route
# ---------------------------------------------------------------------------

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        if nickname and User.query.filter(
            User.nickname == nickname, User.id != current_user.id
        ).first():
            flash('이미 사용 중인 닉네임입니다.', 'danger')
            return render_template('auth/profile.html')
        current_user.nickname = nickname if nickname else None
        db.session.commit()
        flash('닉네임이 저장되었습니다.', 'success')
        return redirect(url_for('profile'))
    return render_template('auth/profile.html')


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route('/admin/members')
@login_required
@admin_required
def admin_members():
    members = User.query.order_by(User.created_at.asc()).all()
    return render_template('admin/members.html', members=members)


@app.route('/admin/members/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def admin_toggle_active(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash('자기 자신의 활성화 상태는 변경할 수 없습니다.', 'warning')
        return redirect(url_for('admin_members'))

    user.is_active = not user.is_active
    db.session.commit()

    status = '활성화' if user.is_active else '비활성화'
    flash(f'{user.username} 계정이 {status}되었습니다.', 'success')
    return redirect(url_for('admin_members'))


@app.route('/admin/members/<int:user_id>/toggle-role', methods=['POST'])
@login_required
@admin_required
def admin_toggle_role(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash('자기 자신의 역할은 변경할 수 없습니다.', 'warning')
        return redirect(url_for('admin_members'))

    user.role = 'member' if user.role == 'admin' else 'admin'
    db.session.commit()

    flash(f'{user.username}의 역할이 {user.role}(으)로 변경되었습니다.', 'success')
    return redirect(url_for('admin_members'))


# ---------------------------------------------------------------------------
# JWT API helpers / decorators
# ---------------------------------------------------------------------------

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        user = db.session.get(User, payload.get('user_id'))
        if user is None or not user.is_active:
            return jsonify({'error': 'User not found or inactive'}), 401
        return f(user, *args, **kwargs)
    return decorated


def api_admin_required(f):
    @wraps(f)
    def decorated(current_api_user, *args, **kwargs):
        if not current_api_user.is_admin():
            return jsonify({'error': 'Admin access required'}), 403
        return f(current_api_user, *args, **kwargs)
    return decorated


def make_token(user):
    payload = {
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=30),
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


# ---------------------------------------------------------------------------
# API – Authentication
# ---------------------------------------------------------------------------

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'username and password are required'}), 400

    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        return jsonify({'error': 'Invalid username or password'}), 401
    if not user.is_active:
        return jsonify({'error': 'Account is not active'}), 403

    token = make_token(user)
    return jsonify({
        'token': token,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
        },
    })


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'error': 'username, email, and password are required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already in use'}), 409

    user = User(username=username, email=email, role='member', is_active=False)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registration successful. Await admin approval.'}), 201


@app.route('/api/auth/me', methods=['GET'])
@token_required
def api_me(current_api_user):
    u = current_api_user
    return jsonify({
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'role': u.role,
        'is_active': u.is_active,
        'created_at': u.created_at.isoformat(),
    })


# ---------------------------------------------------------------------------
# API – Posts
# ---------------------------------------------------------------------------

@app.route('/api/posts', methods=['GET'])
@token_required
def api_posts_list(current_api_user):
    page = request.args.get('page', 1, type=int)
    per_page = app.config.get('POSTS_PER_PAGE', 15)
    pagination = (
        Post.query
        .order_by(Post.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    posts_data = []
    for post in pagination.items:
        posts_data.append({
            'id': post.id,
            'title': post.title,
            'author': post.author.display_name,
            'created_at': post.created_at.isoformat(),
            'view_count': post.view_count,
            'has_attachments': post.attachments.count() > 0,
            'comment_count': post.comments.count(),
        })
    return jsonify({
        'posts': posts_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': pagination.page,
    })


@app.route('/api/posts/<int:post_id>', methods=['GET'])
@token_required
def api_post_detail(current_api_user, post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({'error': 'Post not found'}), 404

    post.view_count += 1
    db.session.commit()

    attachments = [{
        'id': a.id,
        'original_filename': a.original_filename,
        'file_size': a.file_size,
    } for a in post.attachments.all()]

    comments = [{
        'id': c.id,
        'content': c.content,
        'author': c.author.display_name,
        'created_at': c.created_at.isoformat(),
    } for c in post.comments.order_by(Comment.created_at.asc()).all()]

    return jsonify({
        'id': post.id,
        'title': post.title,
        'content': post.content,
        'author': post.author.display_name,
        'created_at': post.created_at.isoformat(),
        'updated_at': post.updated_at.isoformat(),
        'view_count': post.view_count,
        'attachments': attachments,
        'comments': comments,
    })


@app.route('/api/posts', methods=['POST'])
@token_required
def api_post_create(current_api_user):
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if not title:
        return jsonify({'error': 'title is required'}), 400
    if not content:
        return jsonify({'error': 'content is required'}), 400

    post = Post(title=title, content=content, author_id=current_api_user.id)
    db.session.add(post)
    db.session.flush()

    files = request.files.getlist('files[]')
    for f in files:
        result = save_uploaded_file(f)
        if result is None:
            continue
        stored_name, original_name, size, file_url = result
        db.session.add(Attachment(
            post_id=post.id,
            filename=stored_name,
            original_filename=original_name,
            file_size=size,
            file_url=file_url,
        ))

    db.session.commit()
    return jsonify({'id': post.id}), 201


@app.route('/api/posts/<int:post_id>', methods=['PUT'])
@token_required
def api_post_update(current_api_user, post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({'error': 'Post not found'}), 404
    if post.author_id != current_api_user.id and not current_api_user.is_admin():
        return jsonify({'error': 'Forbidden'}), 403

    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()

    if not title:
        return jsonify({'error': 'title is required'}), 400
    if not content:
        return jsonify({'error': 'content is required'}), 400

    post.title = title
    post.content = content
    post.updated_at = datetime.utcnow()

    # Delete requested attachments
    delete_ids = request.form.getlist('delete_attachment_ids[]')
    for att_id in delete_ids:
        att = db.session.get(Attachment, int(att_id))
        if att and att.post_id == post.id:
            delete_uploaded_file(att)
            db.session.delete(att)

    # Add new files
    files = request.files.getlist('files[]')
    for f in files:
        result = save_uploaded_file(f)
        if result is None:
            continue
        stored_name, original_name, size, file_url = result
        db.session.add(Attachment(
            post_id=post.id,
            filename=stored_name,
            original_filename=original_name,
            file_size=size,
            file_url=file_url,
        ))

    db.session.commit()
    return jsonify({'message': 'Post updated'})


@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def api_post_delete(current_api_user, post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({'error': 'Post not found'}), 404
    if post.author_id != current_api_user.id and not current_api_user.is_admin():
        return jsonify({'error': 'Forbidden'}), 403

    for att in post.attachments.all():
        delete_uploaded_file(att)

    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Post deleted'})


# ---------------------------------------------------------------------------
# API – Comments
# ---------------------------------------------------------------------------

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def api_comment_create(current_api_user, post_id):
    post = db.session.get(Post, post_id)
    if post is None:
        return jsonify({'error': 'Post not found'}), 404

    data = request.get_json(silent=True) or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'content is required'}), 400

    comment = Comment(post_id=post_id, author_id=current_api_user.id, content=content)
    db.session.add(comment)
    db.session.commit()
    return jsonify({'id': comment.id}), 201


@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@token_required
def api_comment_delete(current_api_user, comment_id):
    comment = db.session.get(Comment, comment_id)
    if comment is None:
        return jsonify({'error': 'Comment not found'}), 404
    if comment.author_id != current_api_user.id and not current_api_user.is_admin():
        return jsonify({'error': 'Forbidden'}), 403

    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Comment deleted'})


# ---------------------------------------------------------------------------
# API – File download
# ---------------------------------------------------------------------------

@app.route('/api/download/<path:filename>')
@token_required
def api_download_file(current_api_user, filename):
    att = Attachment.query.filter_by(filename=filename).first_or_404()
    if att.file_url:
        return redirect(att.file_url)
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        att.filename,
        as_attachment=True,
        download_name=att.original_filename,
    )


# ---------------------------------------------------------------------------
# API – Admin
# ---------------------------------------------------------------------------

@app.route('/api/admin/members', methods=['GET'])
@token_required
@api_admin_required
def api_admin_members(current_api_user):
    members = User.query.order_by(User.created_at.asc()).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'role': u.role,
        'is_active': u.is_active,
        'created_at': u.created_at.isoformat(),
    } for u in members])


@app.route('/api/admin/members/<int:user_id>/toggle-active', methods=['POST'])
@token_required
@api_admin_required
def api_admin_toggle_active(current_api_user, user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({'error': 'User not found'}), 404
    if user.id == current_api_user.id:
        return jsonify({'error': 'Cannot change your own active status'}), 400

    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'id': user.id, 'is_active': user.is_active})


@app.route('/api/admin/members/<int:user_id>/toggle-role', methods=['POST'])
@token_required
@api_admin_required
def api_admin_toggle_role(current_api_user, user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({'error': 'User not found'}), 404
    if user.id == current_api_user.id:
        return jsonify({'error': 'Cannot change your own role'}), 400

    user.role = 'member' if user.role == 'admin' else 'admin'
    db.session.commit()
    return jsonify({'id': user.id, 'role': user.role})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
