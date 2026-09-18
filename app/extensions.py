"""Flask extensions shared across the whole application.

Central module so models, services and blueprints can all import the
same ``db`` / ``login_manager`` instances without circular imports.
"""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()