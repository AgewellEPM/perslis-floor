"""Ed25519 signature VERIFICATION (RFC 8032 §5.1.7). Standard library only.

This is the RFC 8032 §6 reference arithmetic, trimmed to what verification
needs, and pinned by the RFC's own test vectors in the test suite. It is not
constant-time, which does not matter here: verification handles only public
data (a public key, a message, a signature). Signing is not in this package.

Why asymmetric: with a shared HMAC key, whoever can verify a spec can also
forge one. With Ed25519 the runtime holds only a public key — it can check that
Perslis admitted a spec, and cannot mint one.
"""
from __future__ import annotations

import hashlib

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493   # group order


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)


def sha512_modq(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % Q


def point_add(a: tuple, b: tuple) -> tuple:
    """Extended twisted-Edwards addition (X, Y, Z, T)."""
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    Dd = 2 * a[2] * b[2] % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def point_mul(s: int, pt: tuple) -> tuple:
    acc = (0, 1, 1, 0)                       # neutral element
    while s > 0:
        if s & 1:
            acc = point_add(acc, pt)
        pt = point_add(pt, pt)
        s >>= 1
    return acc


def point_equal(a: tuple, b: tuple) -> bool:
    return ((a[0] * b[2] - b[0] * a[2]) % P == 0
            and (a[1] * b[2] - b[1] * a[2]) % P == 0)


def _recover_x(y: int, sign: int):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * _SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
BASE = (_GX, _GY, 1, _GX * _GY % P)


def point_compress(pt: tuple) -> bytes:
    zinv = _inv(pt[2])
    x, y = pt[0] * zinv % P, pt[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def point_decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True only for a valid signature by the holder of `public`'s secret."""
    if len(public) != 32 or len(signature) != 64:
        return False
    A = point_decompress(public)
    if A is None:
        return False
    Rs = signature[:32]
    R = point_decompress(Rs)
    if R is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= Q:
        return False
    h = sha512_modq(Rs + public + message)
    return point_equal(point_mul(s, BASE), point_add(R, point_mul(h, A)))
