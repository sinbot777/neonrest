from flask import Blueprint

vibes_bp = Blueprint('vibes', __name__)

@vibes_bp.route("/vibes")
def show_vibes():
    return "Vibes Page"
