from flask import render_template, current_app as flask_app
from flask_mail import Message

from app.extensions import mail


def send_email(subject, sender, recipients, text_body, html_body):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    mail.send(msg)


def send_password_reset_email(user, token):
    send_email("[Epimatch] Reset Your Password",
               sender=flask_app.config["MAIL_USERNAME"],
               recipients=[user.email],
               # will look for in `templates` folder by default
               text_body=render_template('email/reset_password.txt',
                                         user=user, token=token),
               html_body=render_template('email/reset_password.html',
                                         user=user, token=token)
               )
