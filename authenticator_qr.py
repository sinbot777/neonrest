"""Local authenticator enrollment QR images; never writes or transmits the key."""
import base64
import io
import re
from urllib.parse import quote, urlencode


def provisioning_uri(secret, account, issuer='Neonrest'):
    if not isinstance(secret, str) or not re.fullmatch(r'[A-Z2-7]{16,64}', secret):
        raise ValueError('Invalid pending authenticator key')
    # Colons are reserved for the issuer separator in authenticator labels.
    account = str(account).replace(':', '_')
    if not account or len(account) > 100 or issuer not in ('Neonrest', 'Neonrest Sandbox'):
        raise ValueError('Invalid authenticator account label')
    label = quote(issuer + ':' + account, safe='')
    parameters = urlencode({'secret': secret, 'issuer': issuer, 'algorithm': 'SHA1', 'digits': 6, 'period': 30}, quote_via=quote)
    return 'otpauth://totp/' + label + '?' + parameters


def enrollment_image(secret, account, issuer='Neonrest'):
    import qrcode
    from qrcode.image.pil import PilImage
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(provisioning_uri(secret, account, issuer))
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(image_factory=PilImage, fill_color='black', back_color='white').save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
