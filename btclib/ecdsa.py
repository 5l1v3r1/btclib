#!/usr/bin/env python3

""" Elliptic Curve Digital Signature Algorithm

http://www.secg.org/sec1-v2.pdf
"""

from hashlib import sha256
from typing import List, Optional

from btclib.numbertheory import mod_inv
from btclib.ellipticcurves import Union, Tuple, \
                                  Scalar, Point, GenericPoint, \
                                  EllipticCurve, secp256k1, \
                                  pointMultiply, DoubleScalarMultiplication, \
                                  int_from_Scalar, to_Point
from btclib.rfc6979 import rfc6979
from btclib.ecsignutils import HashDigest, bytes_from_hash, int_from_hash

ECDS = Tuple[Scalar, Scalar]

def ecdsa_sign(M: bytes,
               q: Scalar,
               k: Optional[Scalar] = None,
               ec: EllipticCurve = secp256k1,
               Hash = sha256) -> Tuple[int, int]:
    """ECDSA signing operation according to SEC 2

    See section 4.1.3
    """
    H = Hash(M).digest()
    return _ecdsa_sign(H, q, k, ec, Hash)

# Private function provided for testing purposes only.
# To avoid forgeable signature, sign and verify should
# always use the message, not its hash digest.
def _ecdsa_sign(H: HashDigest,
                d: Scalar,
                k: Optional[Scalar] = None,
                ec: EllipticCurve = secp256k1,
                Hash = sha256) -> Tuple[int, int]:
    # ECDSA signing operation according to SEC 2
    # See section 4.1.3

    # The message digest m: a 32-byte array
    # checked below inside int_from_hash()

    # The secret key d: an integer in the range 1..n-1.
    d = int_from_Scalar(ec, d)
    if d == 0:
        raise ValueError("invalid (zero) private key")

    # Fail if k' = 0.
    if k is None:
        k = rfc6979(d, H, ec, Hash)                        # 1
    else:
        k = int_from_Scalar(ec, k)

    # Let R = k'G.
    R = pointMultiply(ec, k, ec.G)                         # 1
    if R[1] == 0:
        raise ValueError("ephemeral key k=0 in ecdsa sign operation")

    xR = R[0]                                              # 2
    r = xR % ec.n                                          # 3
    if r==0: # required as in verification it will multiply the public key
        raise ValueError("r = 0, failed to sign")
    # already got H as input                               # 4
    e = int_from_hash(H, ec, Hash)                         # 5
    s = mod_inv(k, ec.n) * (e + r*d) % ec.n                # 6
    if s==0: # required as in verification the inverse of s is needed
        raise ValueError("s = 0, failed to sign")
    return r, s

def ecdsa_verify(dsasig: ECDS,
                 M: bytes,
                 Q: GenericPoint,
                 ec: EllipticCurve = secp256k1,
                 Hash = sha256) -> bool:
    """ECDSA veryfying operation to SEC 2

    See section 4.1.4
    """
    try:
        H = Hash(M).digest()
        return _ecdsa_verify(dsasig, H, Q, ec, Hash)
    except Exception:
        return False

# Private function provided for testing purposes only.
# To avoid forgeable signature, sign and verify should
# always use the message, not its hash digest.
def _ecdsa_verify(dsasig: ECDS,
                  H: HashDigest,
                  P: GenericPoint,
                  ec: EllipticCurve = secp256k1,
                  Hash = sha256) -> bool:
    # ECDSA veryfying operation to SEC 2
    # See section 4.1.4

    # Fail if r is not [1, n-1]
    # Fail if s is not [1, n-1]
    r, s = to_dsasig(dsasig, ec)                        # 1

    # H already provided as input                       # 2
    # The message digest m: a 32-byte array
    e = int_from_hash(H, ec, Hash)                      # 3

    # Let P = point(pk); fail if point(pk) fails.
    P = to_Point(ec, P)

    s1 = mod_inv(s, ec.n); u1 = e*s1; u2 = r*s1         # 4
    R = DoubleScalarMultiplication(ec, u1, ec.G, u2, P) # 5

    # Fail if infinite(R) or r ≠ x(R) %n.
    if R[1] == 0:
        return False
    xR = R[0]                                           # 6
    v = xR % ec.n                                       # 7
    return v == r                                       # 8

def ecdsa_pubkey_recovery(dsasig: ECDS,
                          M: bytes,
                          ec: EllipticCurve = secp256k1,
                          Hash = sha256) -> List[Point]:
    """ECDSA public key recovery operation according to SEC 2

    See section 4.1.6
    """
    H = Hash(M).digest()
    return _ecdsa_pubkey_recovery(dsasig, H, ec, Hash)

# Private function provided for testing purposes only.
# To avoid forgeable signature, sign and verify should
# always use the message, not its hash digest.
def _ecdsa_pubkey_recovery(dsasig: ECDS,
                           H: HashDigest,
                           ec: EllipticCurve = secp256k1,
                           Hash = sha256) -> List[Point]:
    # ECDSA public key recovery operation according to SEC 2
    # See section 4.1.6

    # The message digest m: a 32-byte array
    # checked below inside int_from_hash()

    r, s = to_dsasig(dsasig, ec)

    # precomputations
    e = int_from_hash(H, ec, Hash) # ECDSA verification step 3
    r1 = mod_inv(r, ec.n)
    r1s = r1*s
    r1e =-r1*e
    keys = []
    for j in range(0, 2): # FIXME: use ec.cofactor+1 instead of 2
        x = r + j*ec.n # 1.1
        try:
            R = (x, ec.yOdd(x, 1)) # 1.2, 1.3, and 1.4
            # 1.5 already taken care outside this for loop
            Q = DoubleScalarMultiplication(ec, r1s, R, r1e, ec.G) # 1.6.1
            # 1.6.2 is always satisfied for us, and we do not stop here
            keys.append(Q)
            R = ec.opposite(R)                                    # 1.6.3
            Q = DoubleScalarMultiplication(ec, r1s, R, r1e, ec.G)
            keys.append(Q)
        except Exception: # can't get a curve's point
            pass
    return keys

def to_dsasig(dsasig: ECDS,
              ec: EllipticCurve = secp256k1) -> Tuple[int, int]:
    """check DSA signature format is correct and return the signature itself"""

    if len(dsasig) != 2:
        m = "invalid length %s for ECDSA signature" % len(dsasig)
        raise TypeError(m)

    r = int(dsasig[0])
    if not (0 < r < ec.n):
        raise ValueError("r not in [1, n-1]")

    s = int(dsasig[1])
    if not (0 < s < ec.n):
        raise ValueError("s not in [1, n-1]")

    return r, s
