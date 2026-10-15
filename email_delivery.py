"""Bounded account mail delivery, safe retry classification and redacted operations records."""
import smtplib,ssl
from flask import current_app
from flask_mail import Connection

class BoundedConnection(Connection):
    def configure_host(self):
        timeout=max(1,min(20,float(current_app.config.get('MAIL_CONNECT_TIMEOUT',8))))
        context=ssl.create_default_context()
        if not (self.mail.use_tls or self.mail.use_ssl):
            raise RuntimeError('Encrypted SMTP is required')
        if self.mail.use_ssl:
            host=smtplib.SMTP_SSL(self.mail.server,self.mail.port,timeout=timeout,context=context)
        else:
            host=smtplib.SMTP(self.mail.server,self.mail.port,timeout=timeout)
        try:
            # SMTP debug output can contain addresses, credentials and recovery links.
            host.set_debuglevel(0)
            if self.mail.use_tls:
                host.starttls(context=context)
            if self.mail.username and self.mail.password:
                if not (self.mail.use_tls or self.mail.use_ssl):
                    raise RuntimeError('Encrypted SMTP is required')
                host.login(self.mail.username,self.mail.password)
            return host
        except Exception:
            host.close()
            raise

    def __exit__(self,exc_type,exc_value,tb):
        # DATA's success reply is the acceptance boundary. A later failed QUIT must
        # not relabel an accepted message as failed or cause duplicate retries.
        if self.host is not None:
            try:self.host.close()
            except (OSError,smtplib.SMTPException):
                current_app.logger.warning('SMTP connection cleanup failed after delivery attempt')


def retryable(exc):
    # Only an explicit temporary SMTP rejection is safe to retry. A timeout or
    # disconnect may have happened after the server accepted DATA: never retry it.
    if isinstance(exc,smtplib.SMTPRecipientsRefused):
        return bool(exc.recipients) and all(400<=code<500 for code,_ in exc.recipients.values())
    return isinstance(exc,(smtplib.SMTPConnectError,smtplib.SMTPHeloError,
        smtplib.SMTPAuthenticationError,smtplib.SMTPSenderRefused,smtplib.SMTPDataError)) and 400<=exc.smtp_code<500


def install(app,core):
    original_send=core.mail.send
    original_connect=core.mail.connect
    core.mail.connect=lambda:BoundedConnection(original_connect().mail)
    app.config.setdefault('MAIL_CONNECT_TIMEOUT',8)
    def record(outcome,attempts,error=None):
        # Fixed fields only; never log SMTP reply text, addresses, bodies or tokens.
        detail=f'Account email {outcome}; attempts={attempts}'
        if error:detail+='; error='+type(error).__name__
        try:
            db=core.get_db();db.execute("INSERT INTO operations_events(kind,detail) VALUES ('email',?)",(detail,));db.commit()
        except Exception:
            app.logger.error('Could not record account email delivery outcome')
    def monitored_send(message):
        for attempt in (1,2):
            try:
                result=original_send(message)
                if result is False:
                    record('failed',attempt);return False
                record('accepted',attempt);return True
            except Exception as exc:
                if attempt==1 and retryable(exc):
                    continue
                record('failed',attempt,exc)
                app.logger.warning('Account email delivery failed (%s)',type(exc).__name__)
                return False
    core.mail.send=monitored_send


def deliver(core,message):
    # Route tests replace mail.send directly, so retain the same failure contract.
    try:
        return core.mail.send(message) is not False
    except Exception as exc:
        current_app.logger.warning('Account email delivery failed (%s)',type(exc).__name__)
        return False


def finish_token_delivery(db,table,token_hash,accepted):
    """used=2 is pending SMTP, 0 is usable, 1 is cancelled/used/failed."""
    if table not in ('email_verifications','password_resets'):
        raise ValueError('Unsupported recovery table')
    with db:
        row=db.execute(f'SELECT rowid AS sequence,user_id FROM {table} WHERE token_hash=?',(token_hash,)).fetchone()
        if not row:return
        if not accepted:
            db.execute(f'UPDATE {table} SET used=1 WHERE token_hash=? AND used=2',(token_hash,));return
        activated=db.execute(f'UPDATE {table} SET used=0 WHERE token_hash=? AND used=2',(token_hash,))
        if activated.rowcount:
            # A successful newer send cancels older pending sends as well. A slow
            # completion cannot resurrect a cancelled token or supersede it.
            db.execute(f'UPDATE {table} SET used=1 WHERE user_id=? AND rowid<?',(row['user_id'],row['sequence']))
