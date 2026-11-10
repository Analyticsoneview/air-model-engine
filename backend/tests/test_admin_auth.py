import base64, hashlib, hmac, struct
from app.admin_auth import verify_totp

def _totp(secret: str, timestamp: int) -> str:
    key=base64.b32decode(secret + "="*((8-len(secret)%8)%8))
    counter=timestamp//30
    digest=hmac.new(key,struct.pack(">Q",counter),hashlib.sha1).digest()
    offset=digest[-1]&15
    value=(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000
    return f"{value:06d}"

def test_totp_accepts_current_code_and_clock_skew():
    secret="JBSWY3DPEHPK3PXP"
    assert verify_totp(secret,_totp(secret,1_800_000_000),now=1_800_000_000)
    assert verify_totp(secret,_totp(secret,1_800_000_000),now=1_800_000_030)

def test_totp_rejects_invalid_codes():
    assert not verify_totp("JBSWY3DPEHPK3PXP","12345",now=1_800_000_000)
    assert not verify_totp("JBSWY3DPEHPK3PXP","abcdef",now=1_800_000_000)
