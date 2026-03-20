import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _fix_db_url(url):
    """Railway provides postgres://, SQLAlchemy 2.x needs postgresql://"""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'bmse-bulletin-board-secret-key-change-in-production'

    SQLALCHEMY_DATABASE_URI = _fix_db_url(
        os.environ.get('DATABASE_URL') or
        'sqlite:///' + os.path.join(BASE_DIR, 'bmse_board.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    ALLOWED_EXTENSIONS = {
        'pdf', 'doc', 'docx', 'xls', 'xlsx',
        'ppt', 'pptx', 'hwp', 'zip',
        'jpg', 'jpeg', 'png', 'gif'
    }

    POSTS_PER_PAGE = 10

    # Cloudinary – set these env vars in Railway to enable cloud file storage
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')
