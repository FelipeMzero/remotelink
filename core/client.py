"""
RemoteLink - Client (Viewer) Module
Dois sockets separados:
  - _frame_sock: recebe frames do servidor (leitura contínua)
  - _input_sock: envia input ao servidor  (escrita sob demanda, TCP_NODELAY)
Suporte a Rede Externa (WAN/UPnP/Cloud Rendezvous + Conexão Reversa) e
Input de baixa latência estilo AnyDesk (VK/Scancode/Unicode + coordenadas normalizadas).
"""

import socket
import threading
import struct
import json
import time
import uuid
import logging
import platform
import re
import queue
from typing import Callable, Optional

logger = logging.getLogger("remotelink.client")

FRAME_PORT      = 52340
INPUT_PORT      = 52341
PROTO_VER       = 1
CONNECT_TIMEOUT = 8.0
PROBE_TIMEOUT   = 3.5


def normalize_code(code: str) -> str:
    return re.sub(r'[^0-9]', '', code)


# ── Probe ─────────────────────────────────────────────────────────────────────

def _recv_exact_s(sock: socket.socket, n: int, timeout: float) -> Optional[bytes]:
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        except Exception:
            return None
    return buf


def probe_target(ip: str, port: int = FRAME_PORT,
                 timeout: float = PROBE_TIMEOUT) -> dict:
    base = {"ip": ip, "port": port, "reachable": False}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))

        hello = json.dumps({
            "version": PROTO_VER, "access_code": "",
            "probe": True, "session_id": "",
        }).encode()
        s.sendall(struct.pack(">I", len(hello)) + hello)

        hdr = _recv_exact_s(s, 4, timeout)
        if not hdr:
            s.close()
            return {**base, "error": "sem resposta"}
        n = struct.unpack(">I", hdr)[0]
        if not (0 < n < 65536):
            s.close()
            return {**base, "error": "inválido"}
        raw = _recv_exact_s(s, n, timeout)
        s.close()
        if not raw:
            return {**base, "error": "dados incompletos"}
        resp = json.loads(raw)
        m = resp.get("machine", {})
        m["reachable"] = True
        m["ip"]        = ip
        m["port"]      = port
        return m
    except socket.timeout:
        return {**base, "error": "timeout"}
    except ConnectionRefusedError:
        return {**base, "error": "recusado"}
    except Exception as e:
        return {**base, "error": str(e)}


def probe_any_port(ip: str, ports: list[int] = None,
                   timeout: float = 2.2) -> dict:
    """Testa simultaneamente todas as portas abertas candidatas e retorna a primeira que responder."""
    from core.identity import CANDIDATE_OPEN_PORTS
    cand_ports = list(dict.fromkeys((ports or []) + list(CANDIDATE_OPEN_PORTS)))
    winner = {}
    win_ev = threading.Event()
    lock = threading.Lock()

    def _try(p: int):
        if win_ev.is_set():
            return
        r = probe_target(ip, port=p, timeout=timeout)
        if r.get("reachable"):
            with lock:
                if not win_ev.is_set():
                    winner.update(r)
                    win_ev.set()

    threads = [
        threading.Thread(target=_try, args=(p,), daemon=True)
        for p in cand_ports
    ]
    for t in threads:
        t.start()
    win_ev.wait(timeout=timeout + 0.3)
    if winner.get("reachable"):
        return winner
    return {"ip": ip, "port": cand_ports[0] if cand_ports else FRAME_PORT,
            "reachable": False, "error": "timeout"}


def resolve_hostname_to_ips(hostname: str, port: int = FRAME_PORT) -> list[str]:
    ips, seen = [], set()
    try:
        for r in socket.getaddrinfo(hostname, port,
                                    socket.AF_INET, socket.SOCK_STREAM):
            ip = r[4][0]
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)
    except Exception:
        try:
            ip = socket.gethostbyname(hostname)
            ips.append(ip)
        except Exception:
            pass
    return ips


def probe_hostname(hostname: str, port: int = FRAME_PORT) -> dict:
    for ip in resolve_hostname_to_ips(hostname, port):
        r = probe_any_port(ip, ports=[port])
        if r.get("reachable"):
            r.setdefault("hostname", hostname)
            return r
    return {"reachable": False, "hostname": hostname, "port": port,
            "error": "Nenhum IP respondeu"}


# ── RemoteLinkClient ──────────────────────────────────────────────────────────

class RemoteLinkClient:
    """
    Cliente RemoteLink com suporte a:
      - Multiplexação em porta única (frames + input no mesmo socket TCP full-duplex)
      - Varredura paralela de portas abertas (52340, 7070, 6568, 8080, 8443, 33890, 443, 80)
      - Relay Externo automático (MQTT over TCP) quando todas as portas estão bloqueadas por CGNAT
      - Conexão Reversa (NAT Traversal)
    """

    def __init__(self,
                 on_frame:         Callable = None,
                 on_connected:     Callable = None,
                 on_disconnected:  Callable = None,
                 on_status_change: Callable = None,
                 on_error:         Callable = None):
        self.on_frame         = on_frame
        self.on_connected     = on_connected
        self.on_disconnected  = on_disconnected
        self.on_status_change = on_status_change
        self.on_error         = on_error

        self._frame_sock: Optional[socket.socket] = None
        self._input_sock: Optional[socket.socket] = None
        self._relay_sock  = None
        self._relay_topics: dict = {}
        self._relay_mode  = False
        self._input_lock  = threading.Lock()
        self._input_queue: queue.Queue = queue.Queue(maxsize=300)
        self._running     = False
        self._connected   = False
        self.remote_info: Optional[dict] = None
        self._session_id  = ""
        self._last_ack_ts = 0.0
        self.session_fingerprint = ""
        self.pow_hash = ""
        self.permissions: dict = {"keyboard_mouse": True, "audio": True, "mic": True}
        self._sound_enabled: bool = True
        self._mic_enabled: bool = False
        self._audio_capture = None
        self._audio_playback = None
        self._quality_mode: str = "high"

    def _start_workers(self, start_recv: bool = True):
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
            except Exception:
                break
        if start_recv:
            threading.Thread(target=self._recv_loop,
                             daemon=True, name="RL-Recv").start()
        threading.Thread(target=self._input_sender_loop,
                         daemon=True, name="RL-InputSend").start()

    # ── Connect (Direto LAN / WAN em Porta Única ou Dupla) ────────────────

    def connect(self, ip: str, port: int = FRAME_PORT,
                access_code: str = "",
                local_access_code: str = "",
                timeout: float = CONNECT_TIMEOUT,
                silent_error: bool = False) -> bool:
        self._notify_status("connecting")
        try:
            fsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            fsock.settimeout(timeout)
            fsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            fsock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                fsock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
            except Exception:
                pass
            fsock.connect((ip, port))

            pow_nonce = 0
            pow_hash = ""
            try:
                from core.crypto import generate_pow_challenge, solve_proof_of_work
                pow_ch = generate_pow_challenge(normalize_code(access_code))
                pow_nonce, pow_hash = solve_proof_of_work(pow_ch, difficulty=4)
            except Exception as e:
                logger.debug(f"pow error: {e}")
                pow_ch = ""

            hello = json.dumps({
                "version":       PROTO_VER,
                "access_code":   normalize_code(access_code),
                "viewer_code":   normalize_code(local_access_code),
                "viewer_name":   socket.gethostname(),
                "client_os":     platform.system(),
                "pow_challenge": pow_ch,
                "pow_nonce":     pow_nonce,
                "pow_hash":      pow_hash,
                "probe":         False,
                "session_id":    "",
            }).encode()
            self._send_raw(fsock, hello)

            # Aguarda aprovação do usuário remoto (até 40s)
            fsock.settimeout(40.0)
            resp_raw = self._recv_raw(fsock)
            if not resp_raw:
                fsock.close()
                if not silent_error:
                    self._notify_error("Sem resposta do servidor")
                return False

            resp = json.loads(resp_raw)
            if resp.get("status") != "accepted":
                reason = resp.get("reason", "Conexão rejeitada pelo usuário remoto")
                fsock.close()
                if not silent_error:
                    self._notify_error(reason)
                return False

            self.permissions = resp.get("permissions", {"keyboard_mouse": True, "audio": True, "mic": True})
            self.remote_info = resp.get("machine", {})
            self.remote_info["ip"] = ip
            self.remote_info["port"] = port
            self.remote_info["mode"] = f"Direto TCP :{port}"
            self._session_id = resp.get("session_id", "")
            input_port       = resp.get("input_port", port + 1)
            single_socket    = bool(resp.get("single_socket", False))

            try:
                from core.crypto import compute_session_fingerprint
                self.session_fingerprint = compute_session_fingerprint(
                    self._session_id, normalize_code(access_code), normalize_code(local_access_code), pow_hash
                )
                self.remote_info["session_fingerprint"] = self.session_fingerprint
                self.remote_info["pow_hash"] = pow_hash
            except Exception:
                pass

            fsock.settimeout(None)
            self._frame_sock = fsock
            self._relay_mode = False

            # Se single_socket=True e estamos em porta alternativa (!=52340), usa mux direto;
            # Na porta 52340 ou quando single_socket=False, tenta 52341 (1.0s) com fallback automático para fsock!
            isock = None
            if not single_socket or port == FRAME_PORT:
                try:
                    cand = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    cand.settimeout(1.0 if single_socket else min(timeout, 2.5))
                    cand.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    cand.connect((ip, input_port))
                    ihello = json.dumps({"session_id": self._session_id}).encode()
                    self._send_raw(cand, ihello)
                    iresp_raw = self._recv_raw(cand)
                    if iresp_raw and json.loads(iresp_raw).get("status") == "ok":
                        cand.settimeout(None)
                        isock = cand
                    else:
                        cand.close()
                except Exception:
                    pass
            self._input_sock = isock or fsock

            self._running   = True
            self._connected = True
            self._start_workers(start_recv=True)

            if self._sound_enabled and self.permissions.get("audio", True):
                self.toggle_sound(True)

            self._notify_status("connected")
            if self.on_connected:
                self.on_connected(self.remote_info)

            logger.info(f"Conectado a {ip}:{port} — session={self._session_id} (mux={self._input_sock is fsock})")
            return True

        except socket.timeout:
            if not silent_error:
                self._notify_error("Tempo de conexão esgotado")
        except ConnectionRefusedError:
            if not silent_error:
                self._notify_error("Conexão recusada — RemoteLink está rodando no alvo?")
        except Exception as e:
            if not silent_error:
                self._notify_error(str(e))
        return False

    # ── Connect via Relay Externo (Funciona mesmo com CGNAT / Portas Fechadas) ─

    def connect_via_relay(self, target_code: str,
                          local_access_code: str = "",
                          timeout: float = 8.5,
                          silent_error: bool = False) -> bool:
        """
        Conecta à máquina remota usando um túnel TCP de saída (MQTT Relay).
        Não exige nenhuma porta de entrada aberta no roteador do Host nem do Viewer!
        """
        from core.identity import MQTTRelaySocket, CloudRegistry
        code = normalize_code(target_code)
        if len(code) != 6:
            if not silent_error:
                self._notify_error("Informe o código de 6 dígitos (ex: 750-789) para usar o Relay Externo")
            return False

        self._notify_status("connecting")
        topics = CloudRegistry.relay_topics_for_code(code)
        sid = str(uuid.uuid4())[:8]
        hs_event = threading.Event()
        hs_result = {}

        def _on_relay_msg(topic: str, payload: bytes):
            try:
                if topic == topics["handshake"] and not hs_event.is_set():
                    msg = json.loads(payload.decode("utf-8", errors="ignore"))
                    if msg.get("session_id") in ("", sid):
                        hs_result.update(msg)
                        hs_event.set()
                elif topic == topics["frame"] and self._running and self._relay_mode:
                    if len(payload) > 9 and payload[0] == 0x01:
                        _, msg_len, ts = struct.unpack(">BII", payload[:9])
                        frame_bytes = payload[9:9 + msg_len]
                        if self.on_frame and frame_bytes:
                            self.on_frame(frame_bytes, ts)
                            now = time.perf_counter()
                            if now - self._last_ack_ts >= 3.0:
                                self._last_ack_ts = now
                                self._send_ctrl({"cmd": "ack", "session_id": self._session_id, "ts": ts})
            except Exception as e:
                logger.debug(f"client relay msg err: {e}")

        relay = MQTTRelaySocket(on_message=_on_relay_msg)
        if not relay.connect(timeout=4.5):
            if not silent_error:
                self._notify_error("Não foi possível alcançar o servidor de Relay Externo")
            return False

        relay.subscribe(topics["handshake"])
        relay.subscribe(topics["frame"])
        time.sleep(0.15)

        pow_nonce = 0
        pow_hash = ""
        try:
            from core.crypto import generate_pow_challenge, solve_proof_of_work
            pow_ch = generate_pow_challenge(code)
            pow_nonce, pow_hash = solve_proof_of_work(pow_ch, difficulty=4)
        except Exception:
            pow_ch = ""

        req_payload = json.dumps({
            "cmd":           "connect",
            "access_code":   code,
            "viewer_code":   normalize_code(local_access_code),
            "viewer_name":   socket.gethostname(),
            "client_os":     platform.system(),
            "pow_challenge": pow_ch,
            "pow_nonce":     pow_nonce,
            "pow_hash":      pow_hash,
            "session_id":    sid,
            "version":       PROTO_VER,
        }).encode("utf-8")

        # Envia o pedido de handshake e aguarda autorização (até timeout)
        relay.publish(topics["ctrl"], req_payload)
        wait_time = max(timeout, 35.0)
        if not hs_event.wait(timeout=2.5):
            relay.publish(topics["ctrl"], req_payload)
            hs_event.wait(timeout=wait_time - 2.5)

        if not hs_event.is_set():
            relay.close()
            if not silent_error:
                self._notify_error(
                    "A máquina remota não respondeu (verifique se o RemoteLink está aberto nela)"
                )
            return False

        if hs_result.get("status") != "accepted":
            relay.close()
            if not silent_error:
                self._notify_error(hs_result.get("reason", "Conexão rejeitada pelo usuário remoto"))
            return False

        self.permissions   = hs_result.get("permissions", {"keyboard_mouse": True, "audio": True, "mic": True})
        self._session_id   = hs_result.get("session_id", sid)
        self.remote_info   = hs_result.get("machine", {})
        self.remote_info["ip"]   = self.remote_info.get("public_ip") or self.remote_info.get("local_ip") or "Relay Externo"
        self.remote_info["port"] = 1883
        self.remote_info["mode"] = "Relay Externo (NAT Bypass)"

        try:
            from core.crypto import compute_session_fingerprint
            self.session_fingerprint = compute_session_fingerprint(
                self._session_id, code, normalize_code(local_access_code), pow_hash
            )
            self.remote_info["session_fingerprint"] = self.session_fingerprint
            self.remote_info["pow_hash"] = pow_hash
        except Exception:
            pass
        self._relay_sock   = relay
        self._relay_topics = topics
        self._relay_mode   = True
        self._running      = True
        self._connected    = True
        self._last_ack_ts  = time.perf_counter()
        self._start_workers(start_recv=False)

        if self._sound_enabled and self.permissions.get("audio", True):
            self.toggle_sound(True)

        threading.Thread(
            target=self._relay_watchdog_loop,
            daemon=True,
            name="RL-RelayWatch",
        ).start()

        self._notify_status("connected")
        if self.on_connected:
            self.on_connected(self.remote_info)
        logger.info(f"Conectado via Relay Externo ao código {code} (session={self._session_id})")
        return True

    def _relay_watchdog_loop(self):
        while self._running and self._relay_mode and self._relay_sock and self._relay_sock.connected:
            time.sleep(0.5)
        if self._running and self._relay_mode:
            self._connected = False
            self._running = False
            self._notify_status("disconnected")
            if self.on_disconnected:
                self.on_disconnected()

    # ── Connect Smart (Multi-Porta Paralela + Relay Externo + Reversa) ────

    def connect_smart(self, target_info: dict,
                      local_access_code: str = "",
                      on_progress: Callable = None) -> bool:
        """
        Estratégia inteligente estilo AnyDesk:
          1. Coleta todos os IPs (LAN, VPN, WAN) e portas abertas candidatas
             (52340, 7070, 6568, 8080, 8443, 33890, 443, 80).
          2. Dispara conexão TCP direta paralela (race) para encontrar qualquer porta aberta em < 2.5s.
          3. Se todas as portas diretas estiverem filtradas por CGNAT/Firewall externo,
             conecta automaticamente via Relay Externo (túnel TCP de saída) ou Conexão Reversa!
        """
        from core.identity import CANDIDATE_OPEN_PORTS, CloudRegistry

        def _prog(msg: str):
            logger.info(f"[connect_smart] {msg}")
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        access_code = normalize_code(target_info.get("access_code", ""))
        primary_port = int(target_info.get("port") or FRAME_PORT)

        # Se temos um código de 6 dígitos mas ainda não consultamos a nuvem, busca metadados atualizados
        if len(access_code) == 6 and not target_info.get("candidates"):
            _prog(f"Localizando máquina {access_code[:3]}-{access_code[3:]} na rede externa...")
            cloud_peer = CloudRegistry.lookup_code(access_code)
            if cloud_peer:
                for k, v in cloud_peer.items():
                    if v and not target_info.get(k):
                        target_info[k] = v

        # Monta lista de IPs candidatos sem duplicatas
        ips = []
        for cand_ip in (
            [target_info.get("ip")]
            + list(target_info.get("candidates") or [])
            + [target_info.get("local_ip")]
            + list(target_info.get("vpn_ips") or [])
            + [target_info.get("public_ip")]
        ):
            if cand_ip and cand_ip not in ips:
                ips.append(cand_ip)

        # Se for hostname, resolve para IPs
        if target_info.get("type") == "hostname" and target_info.get("hostname"):
            for hip in resolve_hostname_to_ips(target_info["hostname"], primary_port):
                if hip not in ips:
                    ips.append(hip)

        # Monta lista de portas abertas candidatas
        ports = []
        for p in ([primary_port] + list(target_info.get("open_ports") or []) + list(CANDIDATE_OPEN_PORTS)):
            try:
                pi = int(p)
                if pi not in ports:
                    ports.append(pi)
            except Exception:
                pass

        # Fase 1: Corrida paralela de portas TCP diretas (LAN / VPN / WAN Port-Forwarded)
        if ips:
            _prog(f"Testando portas abertas ({', '.join(str(p) for p in ports[:5])}...) em {', '.join(ips[:2])}...")
            win_pair = {}
            win_ev = threading.Event()
            lock = threading.Lock()

            def _probe_pair(ip_addr: str, p_num: int):
                if win_ev.is_set():
                    return
                res = probe_target(ip_addr, port=p_num, timeout=2.2)
                if res.get("reachable"):
                    with lock:
                        if not win_ev.is_set():
                            win_pair["ip"] = ip_addr
                            win_pair["port"] = p_num
                            win_pair["info"] = res
                            win_ev.set()

            threads = []
            for ip_addr in ips:
                for p_num in ports:
                    t = threading.Thread(target=_probe_pair, args=(ip_addr, p_num), daemon=True)
                    threads.append(t)
                    t.start()

            win_ev.wait(timeout=2.5)

            if win_pair.get("ip"):
                wip = win_pair["ip"]
                wport = win_pair["port"]
                _prog(f"Porta aberta detectada em {wip}:{wport}! Iniciando sessão...")
                if self.connect(
                    wip, port=wport,
                    access_code=access_code,
                    local_access_code=local_access_code,
                    timeout=5.0,
                    silent_error=bool(access_code),
                ):
                    return True

        # Fase 2: Se temos código de acesso (ou conseguimos descobrir via cache), usa o Relay Externo!
        if len(access_code) == 6:
            _prog("Portas diretas bloqueadas por NAT/Firewall — conectando via Relay Externo...")
            if self.connect_via_relay(
                access_code,
                local_access_code=local_access_code,
                timeout=8.0,
                silent_error=True,
            ):
                return True

            _prog("Tentando Conexão Reversa (NAT Traversal)...")
            if self.connect_via_reverse(
                access_code,
                local_access_code=local_access_code,
                timeout=7.0,
            ):
                return True

        # Se falhou tudo, reporta mensagem clara e útil
        if ips and not access_code:
            self._notify_error(
                f"Tempo de conexão esgotado para {ips[0]}.\n\n"
                "Para conectar fora da rede local sem precisar abrir portas no roteador, "
                "digite o Código de Acesso de 6 dígitos da máquina (ex: 750-789) ou "
                f"CODIGO@{ips[0]}!"
            )
        else:
            self._notify_error(
                "Não foi possível conectar à máquina remota.\n"
                "Verifique se o RemoteLink está aberto e com o servidor ativo no computador de destino."
            )
        return False

    # ── Reverse Connect (NAT Traversal para Rede Externa) ─────────────────

    def connect_via_reverse(self, target_code: str,
                            local_access_code: str = "",
                            listen_port: int = 52345,
                            timeout: float = 10.0) -> bool:
        """
        Abre um listener temporário no Viewer (com UPnP se disponível) e solicita via
        CloudRegistry que o Host se conecte de volta ao Viewer.
        """
        from core.identity import CloudRegistry, UPnPManager, get_public_ip, get_all_local_ips

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            srv.bind(("0.0.0.0", listen_port))
        except OSError:
            srv.bind(("0.0.0.0", 0))
            listen_port = srv.getsockname()[1]
        srv.listen(2)
        srv.settimeout(timeout)

        try:
            UPnPManager.forward_ports((listen_port,))
        except Exception:
            pass

        endpoints = []
        pub_ip = get_public_ip()
        if pub_ip:
            endpoints.append(pub_ip)
        for lip in get_all_local_ips():
            if lip not in endpoints:
                endpoints.append(lip)

        token = str(uuid.uuid4())[:8]
        CloudRegistry.send_reverse_request(target_code, endpoints, listen_port, token)

        try:
            fsock, addr = srv.accept()
            fsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            fsock.settimeout(6.0)

            hello = json.dumps({
                "version":     PROTO_VER,
                "access_code": normalize_code(target_code),
                "viewer_code": normalize_code(local_access_code),
                "probe":       False,
                "session_id":  "",
                "reverse_token": token,
            }).encode()
            self._send_raw(fsock, hello)

            resp_raw = self._recv_raw(fsock)
            if not resp_raw:
                fsock.close()
                return False
            resp = json.loads(resp_raw)
            if resp.get("status") != "accepted":
                fsock.close()
                return False

            self.remote_info = resp.get("machine", {})
            self.remote_info["ip"] = addr[0]
            self.remote_info["mode"] = "Conexão Reversa"
            self._session_id = resp.get("session_id", "")

            fsock.settimeout(None)
            self._frame_sock = fsock
            self._input_sock = fsock
            self._relay_mode = False
            self._running    = True
            self._connected  = True
            self._start_workers(start_recv=True)
            self._notify_status("connected")
            if self.on_connected:
                self.on_connected(self.remote_info)
            return True
        except Exception:
            return False
        finally:
            try:
                srv.close()
            except Exception:
                pass

    def disconnect(self):
        self._running    = False
        self._connected  = False

        if self._audio_capture:
            try:
                self._audio_capture.stop()
            except Exception:
                pass
            self._audio_capture = None

        if self._audio_playback:
            try:
                self._audio_playback.stop()
            except Exception:
                pass
            self._audio_playback = None

        if self._relay_mode and self._relay_sock:
            try:
                self.release_all_inputs()
                self._send_ctrl({"cmd": "disconnect", "session_id": self._session_id})
                self._relay_sock.close()
            except Exception:
                pass
            self._relay_sock = None
            self._relay_mode = False
        if self._input_sock:
            try:
                self.release_all_inputs()
                self._send_ctrl({"cmd": "disconnect"})
                if self._input_sock is not self._frame_sock:
                    self._input_sock.close()
            except Exception:
                pass
            self._input_sock = None
        if self._frame_sock:
            try:
                self._frame_sock.close()
            except Exception:
                pass
            self._frame_sock = None
        self._notify_status("disconnected")
        if self.on_disconnected:
            self.on_disconnected()

    def is_connected(self) -> bool:
        return self._connected

    # ── Áudio e Microfone ──────────────────────────────────────────────────

    def toggle_sound(self, enable: Optional[bool] = None) -> bool:
        if enable is None:
            enable = not self._sound_enabled
        self._sound_enabled = enable
        if enable and self._connected and self.permissions.get("audio", True):
            if self._audio_playback is None:
                try:
                    from core.audio import AudioPlayback
                    self._audio_playback = AudioPlayback()
                    self._audio_playback.start()
                except Exception as e:
                    logger.debug(f"AudioPlayback start: {e}")
            self._send_ctrl({"cmd": "audio_toggle", "enabled": True})
        else:
            if self._audio_playback:
                try:
                    self._audio_playback.stop()
                except Exception:
                    pass
                self._audio_playback = None
            if self._connected:
                self._send_ctrl({"cmd": "audio_toggle", "enabled": False})
        return self._sound_enabled

    def toggle_mic(self, enable: Optional[bool] = None) -> bool:
        if enable is None:
            enable = not self._mic_enabled
        self._mic_enabled = enable
        if enable and self._connected and self.permissions.get("mic", True):
            if self._audio_capture is None:
                try:
                    from core.audio import AudioCapture
                    def _on_chunk(chunk: bytes):
                        if not self._running or not self._connected or not self._mic_enabled:
                            return
                        sock = self._input_sock or self._frame_sock
                        if sock:
                            try:
                                hdr = struct.pack(">BI", 0x05, len(chunk))
                                with self._input_lock:
                                    sock.sendall(hdr + chunk)
                            except Exception:
                                pass
                    self._audio_capture = AudioCapture(on_chunk=_on_chunk, device_type="mic")
                    self._audio_capture.start()
                except Exception as e:
                    logger.debug(f"AudioCapture start: {e}")
        else:
            if self._audio_capture:
                try:
                    self._audio_capture.stop()
                except Exception:
                    pass
                self._audio_capture = None
        return self._mic_enabled

    def set_quality(self, mode: str):
        if mode in ("high", "balanced", "fast"):
            self._quality_mode = mode
            if self._connected:
                self._send_ctrl({"cmd": "set_quality", "mode": mode})

    def is_sound_enabled(self) -> bool:
        return self._sound_enabled

    def is_mic_enabled(self) -> bool:
        return self._mic_enabled

    # ── Input API (Direto e Preciso como no AnyDesk) ──────────────────────

    def send_mouse_move(self, x: int, y: int,
                        nx: Optional[float] = None, ny: Optional[float] = None):
        ev = {"type": "mouse_move", "x": int(x), "y": int(y)}
        if nx is not None and ny is not None:
            ev["nx"] = round(float(nx), 5)
            ev["ny"] = round(float(ny), 5)
        self._send_input(ev)

    def send_mouse_click(self, x: int, y: int, button: str = "left", state: str = "down",
                         nx: Optional[float] = None, ny: Optional[float] = None):
        ev = {
            "type": "mouse_click",
            "x": int(x), "y": int(y),
            "button": button, "state": state,
        }
        if nx is not None and ny is not None:
            ev["nx"] = round(float(nx), 5)
            ev["ny"] = round(float(ny), 5)
        self._send_input(ev)

    def send_mouse_dblclick(self, x: int, y: int,
                            nx: Optional[float] = None, ny: Optional[float] = None):
        self.send_mouse_click(x, y, "left", "down", nx, ny)
        self.send_mouse_click(x, y, "left", "up", nx, ny)
        self.send_mouse_click(x, y, "left", "down", nx, ny)
        self.send_mouse_click(x, y, "left", "up", nx, ny)

    def send_mouse_scroll(self, x: int, y: int, delta: int, dx: int = 0,
                          nx: Optional[float] = None, ny: Optional[float] = None):
        ev = {"type": "mouse_scroll", "x": int(x), "y": int(y), "delta": int(delta)}
        if dx:
            ev["dx"] = int(dx)
        if nx is not None and ny is not None:
            ev["nx"] = round(float(nx), 5)
            ev["ny"] = round(float(ny), 5)
        self._send_input(ev)

    def send_key_down(self, key: str = "", vk: int = 0, scan: int = 0,
                      char: str = "", extended: bool = False):
        ev = {"type": "key_down", "key": key}
        if vk:
            ev["vk"] = int(vk)
        if scan:
            ev["scan"] = int(scan)
        if char:
            ev["char"] = char
        if extended:
            ev["ext"] = True
        self._send_input(ev)

    def send_key_up(self, key: str = "", vk: int = 0, scan: int = 0,
                    extended: bool = False):
        ev = {"type": "key_up", "key": key}
        if vk:
            ev["vk"] = int(vk)
        if scan:
            ev["scan"] = int(scan)
        if extended:
            ev["ext"] = True
        self._send_input(ev)

    def send_hotkey(self, *keys):
        for k in keys:
            self.send_key_down(k)
        for k in reversed(keys):
            self.send_key_up(k)

    def send_text(self, text: str):
        self._send_input({"type": "type_text", "text": text})

    def release_all_inputs(self):
        """Libera todas as teclas e botões pressionados no Host ao sair do foco."""
        self._send_input({"type": "release_all"})

    # ── Internos ──────────────────────────────────────────────────────────

    def _recv_loop(self):
        """Thread dedicada: lê frames do _frame_sock continuamente."""
        sock = self._frame_sock
        try:
            while self._running and sock:
                # Cabeçalho: tipo(1) + tamanho(4) + ts(4) = 9 bytes
                hdr = self._recv_exact_s(sock, 9)
                if not hdr:
                    break
                msg_type, msg_len, ts = struct.unpack(">BII", hdr)
                if msg_len == 0:
                    continue
                if msg_len > 30 * 1024 * 1024:
                    logger.warning(f"Frame enorme: {msg_len}")
                    break
                data = self._recv_exact_s(sock, msg_len)
                if not data:
                    break
                if msg_type == 0x01 and self.on_frame:
                    self.on_frame(data, ts)
                elif msg_type == 0x04:  # Áudio do host
                    if self._sound_enabled and self._audio_playback:
                        self._audio_playback.write(data)
        except Exception as e:
            logger.debug(f"recv_loop: {e}")
        finally:
            self._connected = False
            if self._running:
                self._running = False
                self._notify_status("disconnected")
                if self.on_disconnected:
                    self.on_disconnected()

    def _send_input(self, event: dict):
        """Enfileira evento de input sem bloquear a thread da UI (zero latência e sem travamentos)."""
        if not self._connected:
            return
        try:
            self._input_queue.put_nowait(event)
        except queue.Full:
            # Se a fila encher por pico de movimentos do mouse, preserva eventos de clique/teclado
            if event.get("type") != "mouse_move":
                try:
                    self._input_queue.get_nowait()
                    self._input_queue.put_nowait(event)
                except Exception:
                    pass

    def _input_sender_loop(self):
        """Thread dedicada para envio contínuo dos pacotes de teclado e mouse."""
        while self._running and self._connected:
            try:
                event = self._input_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # Coalescência de mouse_move: se o próximo item na fila também for mouse_move, pega o mais recente
            if event.get("type") == "mouse_move":
                while not self._input_queue.empty():
                    try:
                        nxt = self._input_queue.queue[0]
                        if nxt.get("type") == "mouse_move":
                            event = self._input_queue.get_nowait()
                        else:
                            break
                    except Exception:
                        break

            if self._relay_mode and self._relay_sock:
                try:
                    data = json.dumps(event, separators=(",", ":")).encode("utf-8")
                    hdr  = struct.pack(">BI", 0x02, len(data))
                    self._relay_sock.publish(self._relay_topics.get("input", ""), hdr + data)
                except Exception as e:
                    logger.debug(f"relay _send_input error: {e}")
                continue

            sock = self._input_sock or self._frame_sock
            if not sock:
                continue
            try:
                data = json.dumps(event, separators=(",", ":")).encode("utf-8")
                hdr  = struct.pack(">BI", 0x02, len(data))
                with self._input_lock:
                    sock.sendall(hdr + data)
            except Exception as e:
                logger.warning(f"_input_sender_loop error: {e}")
                if sock is self._input_sock and self._frame_sock and self._input_sock is not self._frame_sock:
                    self._input_sock = self._frame_sock

    def _send_ctrl(self, msg: dict):
        if self._relay_mode and self._relay_sock:
            try:
                data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
                self._relay_sock.publish(self._relay_topics.get("ctrl", ""), data)
            except Exception:
                pass
            return

        sock = self._input_sock or self._frame_sock
        if not sock:
            return
        try:
            data = json.dumps(msg, separators=(",", ":")).encode()
            hdr  = struct.pack(">BI", 0x03, len(data))
            with self._input_lock:
                sock.sendall(hdr + data)
        except Exception:
            pass

    def _send_raw(self, sock: socket.socket, data: bytes):
        sock.sendall(struct.pack(">I", len(data)) + data)

    def _recv_raw(self, sock: socket.socket) -> Optional[bytes]:
        hdr = self._recv_exact_s(sock, 4)
        if not hdr:
            return None
        n = struct.unpack(">I", hdr)[0]
        if n > 10 * 1024 * 1024:
            return None
        return self._recv_exact_s(sock, n)

    def _recv_exact_s(self, sock: socket.socket, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except Exception:
                return None
        return buf

    def _notify_status(self, s: str):
        if self.on_status_change:
            try:
                self.on_status_change(s)
            except Exception:
                pass

    def _notify_error(self, msg: str):
        logger.error(f"Client: {msg}")
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass
