"""
network.py - Server en Client netwerkklassen voor multiplayer
Server is een universele aggregator; alle clients (incl. host-client)
zijn gelijk.
"""

import socket
import pickle
import struct
import threading
import queue
import time

from server_game import ServerGame


class ServerIO(threading.Thread):
    """Headless server: TCP handshake + UDP game data I/O + state relay"""
    def __init__(self, port, max_players=4):
        super().__init__(daemon=True)
        self.port = port
        self.max_players = max_players
        self.running = True

        # TCP for initial handshake
        self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_server.setblocking(False)
        self.tcp_server.bind(('0.0.0.0', port))
        self.tcp_server.listen(max_players)

        # UDP for game data
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.setblocking(False)
        self.udp_socket.bind(('0.0.0.0', port))

        # Connected clients: [(addr, player_id, name)]
        self.clients = []
        self.clients_lock = threading.Lock()

        # Latest inputs per client (player_id → data dict)
        self.inputs = {}

        # Server game state
        self.server_game = ServerGame()

        # Lobby updates for lobby phase
        self.lobby_updates = queue.Queue()

        # Host name for lobby
        self.host_name = "Host"

        # Stale client tracking
        self.last_seen = {}

        # Pending TCP registrations awaiting UDP registration
        self._pending = {}
        self._pending_lock = threading.Lock()
        self.next_id = 0  # First client (host) gets 0

    def run(self):
        while self.running:
            self._accept_tcp()
            self._receive_udp()
            self.server_game.apply_inputs(self.inputs)
            self._send_server_state()
            self._cleanup_stale()

    # ── TCP handshake ──────────────────────────────────────────

    def _accept_tcp(self):
        try:
            sock, addr = self.tcp_server.accept()
            sock.settimeout(3.0)
            size_data = self._recv_all(sock, 4)
            if size_data:
                size = struct.unpack('!I', size_data)[0]
                if 0 < size < 8192:
                    data = self._recv_all(sock, size)
                    if data:
                        try:
                            packet = pickle.loads(data)
                        except Exception:
                            sock.close()
                            return
                        if packet.get("type") == "connect":
                            name = packet.get("name", f"Player {self.next_id}")
                            with self._pending_lock:
                                pid = self.next_id
                                self.next_id += 1
                                self._pending[pid] = name
                            resp = {"type": "accept", "player_id": pid}
                            resp_data = pickle.dumps(resp)
                            sock.sendall(struct.pack('!I', len(resp_data)) + resp_data)
            sock.close()
        except BlockingIOError:
            pass
        except OSError:
            pass

    @staticmethod
    def _recv_all(sock, n):
        data = b''
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
        return data

    # ── UDP receive ────────────────────────────────────────────

    def _receive_udp(self):
        while True:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
            except BlockingIOError:
                return
            except OSError:
                return

            try:
                packet = pickle.loads(data)
            except Exception:
                continue

            ptype = packet.get("type")
            pid = packet.get("player_id", -1)

            if ptype == "register":
                with self._pending_lock:
                    name = self._pending.pop(pid, f"Player {pid}")
                should_broadcast = False
                with self.clients_lock:
                    for c_addr, c_pid, _ in self.clients:
                        if c_pid == pid:
                            break
                    else:
                        if len(self.clients) < self.max_players - 1 or pid == 0:
                            self.clients.append((addr, pid, name))
                            self.lobby_updates.put(("player_joined", pid, name))
                            should_broadcast = True
                            self.server_game.register_player(pid, name)
                if should_broadcast:
                    self._broadcast_lobby()

            elif ptype == "pos_update":
                with self.clients_lock:
                    if not any(c_pid == pid for _, c_pid, _ in self.clients):
                        continue
                self.last_seen[pid] = time.time()
                data = packet.get("data", {})
                self.inputs[pid] = data

            elif ptype == "start_game":
                with self.clients_lock:
                    for c_addr, _, _ in self.clients:
                        try:
                            self.udp_socket.sendto(pickle.dumps({"type": "game_start"}), c_addr)
                        except OSError:
                            pass

            elif ptype == "disconnect":
                should_broadcast = False
                with self.clients_lock:
                    for i, (c_addr, c_pid, c_name) in enumerate(self.clients):
                        if c_pid == pid:
                            self.clients.pop(i)
                            should_broadcast = True
                            break
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                self.lobby_updates.put(("player_left", pid, ""))
                if should_broadcast:
                    self._broadcast_lobby()

            elif ptype == "request_lobby":
                self._broadcast_lobby()

    # ── State relay ────────────────────────────────────────────

    def _send_server_state(self):
        state = self.server_game.get_state()
        if not state:
            return
        data = pickle.dumps(state)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def _broadcast_lobby(self):
        players = self.get_lobby_players()
        packet = {"type": "lobby_info", "players": players}
        data = pickle.dumps(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def set_host_name(self, name):
        self.host_name = name

    def _cleanup_stale(self):
        now = time.time()
        stale = []
        with self.clients_lock:
            for addr, pid, name in self.clients:
                last = self.last_seen.get(pid, now)
                if now - last > 10:
                    stale.append((addr, pid, name))
            for _, pid, name in stale:
                self.clients = [(a, p, n) for a, p, n in self.clients if p != pid]
                self.last_seen.pop(pid, None)
                self.inputs.pop(pid, None)
                self.server_game.remove_player(pid)
                self.lobby_updates.put(("player_left", pid, name))
        if stale:
            self._broadcast_lobby()

    def get_lobby_players(self):
        result = []
        with self.clients_lock:
            for _, pid, name in self.clients:
                result.append((name, pid))
        return result

    def stop(self):
        self.running = False
        try:
            self.udp_socket.close()
            self.tcp_server.close()
        except OSError:
            pass


class NetworkClient:
    """Client-side networking (runs on ALL clients, including host-client)"""
    def __init__(self):
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setblocking(False)
        self.server_addr = None
        self.player_id = -1
        self.connected = False

    def connect(self, host, port, name):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            packet = {"type": "connect", "name": name}
            data = pickle.dumps(packet)
            sock.sendall(struct.pack('!I', len(data)) + data)
            size_data = self._recv_all(sock, 4)
            if size_data:
                size = struct.unpack('!I', size_data)[0]
                if 0 < size < 8192:
                    resp_data = self._recv_all(sock, size)
                    if not resp_data:
                        sock.close()
                        return False
                    try:
                        resp = pickle.loads(resp_data)
                    except Exception:
                        sock.close()
                        return False
                    if resp.get("type") == "accept":
                        self.player_id = resp["player_id"]
                        self.server_addr = (host, port)
                        self.connected = True
                        sock.close()
                        reg = {"type": "register", "player_id": self.player_id}
                        self.udp_socket.sendto(pickle.dumps(reg), self.server_addr)
                        return True
            sock.close()
        except (socket.timeout, ConnectionRefusedError, OSError):
            pass
        return False

    @staticmethod
    def _recv_all(sock, n):
        data = b''
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
        return data

    def send_input(self, input_data):
        if not self.server_addr:
            return
        packet = {"type": "pos_update", "data": input_data, "player_id": self.player_id}
        try:
            self.udp_socket.sendto(pickle.dumps(packet), self.server_addr)
        except OSError:
            pass

    def send(self, packet):
        if not self.server_addr:
            return
        packet["player_id"] = self.player_id
        try:
            self.udp_socket.sendto(pickle.dumps(packet), self.server_addr)
        except OSError:
            pass

    def try_recv(self):
        """Receive any UDP packet. Returns parsed dict or None."""
        try:
            data, addr = self.udp_socket.recvfrom(65536)
            return pickle.loads(data)
        except BlockingIOError:
            return None
        except Exception:
            return None

    def disconnect(self):
        self.connected = False
        self.server_addr = None
        try:
            self.udp_socket.close()
        except OSError:
            pass
