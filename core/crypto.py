"""
RemoteLink - Cryptographic Security & Proof-of-Work (PoW) Module
Proteção anti-brute-force (Hashcash SHA-256) e geração de Fingerprint
criptográfico de sessão para verificação mútua de autenticidade (anti-MITM).
"""

import hashlib
import time
from typing import Tuple


def generate_pow_challenge(access_code: str, session_hint: str = "") -> str:
    """Gera o desafio Proof-of-Work com base no código de acesso e janela de tempo."""
    time_window = int(time.time()) // 120  # Janela de 2 minutos
    return f"RL-POW:{access_code}:{time_window}:{session_hint}"


def solve_proof_of_work(challenge: str, difficulty: int = 4) -> Tuple[int, str]:
    """
    Resolve o desafio Proof-of-Work (Hashcash SHA-256).
    Encontra um nonce tal que SHA256(challenge:nonce) inicie com '0' * difficulty.
    Dificuldade 4 (16 bits) leva ~20-50ms no computador, inviabilizando varreduras de força bruta.
    """
    target = "0" * difficulty
    nonce = 0
    while True:
        digest = hashlib.sha256(f"{challenge}:{nonce}".encode("utf-8")).hexdigest()
        if digest.startswith(target):
            return nonce, digest
        nonce += 1


def verify_proof_of_work(challenge: str, nonce: int, difficulty: int = 4) -> Tuple[bool, str]:
    """Verifica instantaneamente se o nonce resolve o desafio SHA-256."""
    target = "0" * difficulty
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode("utf-8")).hexdigest()
    is_valid = digest.startswith(target)
    return is_valid, digest


def compute_session_fingerprint(session_id: str,
                                host_code: str,
                                viewer_code: str,
                                pow_hash: str = "") -> str:
    """
    Gera um Fingerprint Criptográfico de Sessão único e imutável (16 caracteres hex em 4 blocos).
    Exibido tanto no Host quanto no Viewer para auditoria visual mútua.
    """
    material = f"{session_id}:{host_code}:{viewer_code}:{pow_hash}"
    h = hashlib.sha256(material.encode("utf-8")).hexdigest().upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"
