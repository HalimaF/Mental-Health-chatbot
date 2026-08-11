"""Encryption at rest."""

from __future__ import annotations

from sqlalchemy import text as sql_text

from app.crypto import Encryptor, get_encryptor
from app.extensions import db
from app.models import Conversation, Message, User


def test_roundtrip():
    enc = Encryptor("1EDoBsdzKcSC7Ib7c1p9nQnrLBHXNVOBc1CBBmvBIeY=")
    secret = "I have been feeling hopeless for weeks"
    assert enc.decrypt(enc.encrypt(secret)) == secret


def test_ciphertext_does_not_contain_plaintext():
    enc = Encryptor("1EDoBsdzKcSC7Ib7c1p9nQnrLBHXNVOBc1CBBmvBIeY=")
    blob = enc.encrypt("suicidal thoughts")
    assert "suicidal" not in blob
    assert blob.startswith("enc:v1:")


def test_arbitrary_key_material_is_accepted():
    """A developer pasting a random string should get a working key, not a crash."""
    enc = Encryptor("not-a-valid-fernet-key-just-a-passphrase")
    assert enc.decrypt(enc.encrypt("hello")) == "hello"


def test_wrong_key_does_not_crash_the_page():
    a = Encryptor("1EDoBsdzKcSC7Ib7c1p9nQnrLBHXNVOBc1CBBmvBIeY=")
    b = Encryptor("a-completely-different-key")
    assert "unable to decrypt" in b.decrypt(a.encrypt("private"))


def test_legacy_plaintext_rows_stay_readable():
    """Rows written before encryption existed must not break on read."""
    enc = Encryptor("1EDoBsdzKcSC7Ib7c1p9nQnrLBHXNVOBc1CBBmvBIeY=")
    assert enc.decrypt("an old plaintext message") == "an old plaintext message"


def test_message_content_is_encrypted_in_the_database(app):
    user = User(username="zara", email="zara@example.com")
    user.set_password("Str0ng-Passphrase!42")
    db.session.add(user)
    db.session.commit()

    convo = Conversation(user_id=user.id, title="t")
    db.session.add(convo)
    db.session.commit()

    secret = "I do not want to be here anymore"
    db.session.add(Message(conversation_id=convo.id, role="user", content=secret))
    db.session.commit()

    # Read the raw column, bypassing the SQLAlchemy type decorator entirely.
    raw = db.session.execute(sql_text("SELECT content FROM messages")).scalar()
    assert secret not in raw
    assert raw.startswith("enc:v1:")

    # And it comes back intact through the ORM.
    assert db.session.query(Message).first().content == secret


def test_encryptor_is_wired_up_by_the_factory(app):
    assert get_encryptor().enabled is True
