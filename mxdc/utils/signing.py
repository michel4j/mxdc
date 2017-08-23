import base64
import time

import baseconv
from cryptography.hazmat.primitives import hashes
from cryptography import exceptions


class Signer(object):
    def __init__(self, public_key=None, private_key=None, sep=':', salt=None, max_delta=60):
        assert public_key or private_key, "Must provide either a public key or a private key, or both."
        self.public_key = public_key
        self.private_key = private_key
        self.sep = sep
        self.salt = salt or 'ca.clsi.cmcf'
        self.max_delta = max_delta

    def timestamp(self):
        return baseconv.base62.encode(int(time.time()))

    def signature(self, value):
        signature = self.private_key.sign(
            '{salt}{sep}{value}'.format(salt=self.salt, value=value, sep=self.sep),
            hashes.SHA256()
        )
        return base64.urlsafe_b64encode(signature)

    def sign(self, value):
        assert self.private_key is not None, "Needs private key in order to sign."
        timed_value = '{value}{sep}{timestamp}'.format(value=value, sep=self.sep, timestamp=self.timestamp())
        return '{value}{sep}{signature}'.format(value=timed_value, sep=self.sep, signature=self.signature(timed_value))

    def unsign(self, signed_value):
        if self.sep not in signed_value:
            raise exceptions.InvalidSignature('No "%s" found in value' % self.sep)
        timed_value, b64_sig = signed_value.rsplit(self.sep, 1)
        value, b62_time = timed_value.rsplit(self.sep, 1)
        signature = base64.urlsafe_b64decode(b64_sig)
        signature_time = baseconv.base62.decode(b62_time)
        now = time.time()
        verify_value = '{salt}{sep}{value}'.format(salt=self.salt, value=timed_value, sep=self.sep)
        self.public_key.verify(signature, verify_value, hashes.SHA256())

        if now - signature_time > self.max_delta:
            raise exceptions.InvalidSignature('Signature is too old.')

        return value

