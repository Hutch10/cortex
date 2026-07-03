import os
import nacl.signing
import nacl.encoding
from pathlib import Path

class IdentityService:
    def __init__(self, key_path: str = "outputs/identity.key"):
        self.key_path = Path(key_path)
        self.signing_key = None
        self.verify_key = None
        self._initialize_identity()

    def _initialize_identity(self):
        """Load or create the Ed25519 sovereign identity."""
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.key_path.exists():
            with open(self.key_path, "rb") as f:
                seed = f.read()
                self.signing_key = nacl.signing.SigningKey(seed)
        else:
            self.signing_key = nacl.signing.SigningKey.generate()
            with open(self.key_path, "wb") as f:
                f.write(self.signing_key.encode())
        
        self.verify_key = self.signing_key.verify_key

    def get_public_id(self) -> str:
        """Return the hex encoded public key (The Cortex ID)."""
        return self.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode("utf-8")

    def sign_payload(self, payload: str) -> str:
        """Sign a payload and return the hex signature."""
        signed = self.signing_key.sign(payload.encode("utf-8"))
        return signed.signature.hex()

identity_service = IdentityService()
