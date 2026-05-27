"""
network.py - Server en Client netwerkklassen voor multiplayer
"""

import socket
import pickle
import struct
import threading
import queue
import time


class ServerIO(threading.Thread):
    """Host-side: TCP handshake + UDP game data I/O"""
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

        # Remote clients: [(addr, player_id, name)]
        self.clients = []
        self.clients_lock = threading.Lock()

        # Queues for main-thread communication
        self.input_queue = queue.Queue()     # remote inputs → main thread
        self.state_queue = queue.Queue()     # main thread → send state to clients
        self.outgoing_queue = queue.Queue()  # main thread → send any packet to clients
        self.lobby_updates = queue.Queue()   # lobby changes → main thread

        # Host name
        self.host_name = "Host"

        # Stale client tracking
        self.last_seen = {}       # player_id → time.time()

        # Pending TCP registrations awaiting UDP
        self._pending = {}       # player_id → name
        self._pending_lock = threading.Lock()
        self.next_id = 1         # player_id 0 = host

    def run(self):
        while self.running:
            self._accept_tcp()
            self._receive_udp()
            self._send_state()
            self._send_outgoing()
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
                    data = sock.recv(size)
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

            if ptype == "register":
                pid = packet.get("player_id", -1)
                with self._pending_lock:
                    name = self._pending.pop(pid, f"Player {pid}")
                with self.clients_lock:
                    for c_addr, c_pid, _ in self.clients:
                        if c_pid == pid:
                            break
                    else:
                        if len(self.clients) < self.max_players - 1:
                            self.clients.append((addr, pid, name))
                            self.lobby_updates.put(("player_joined", pid, name))

            elif ptype == "pos_update":
                pid = None
                with self.clients_lock:
                    for c_addr, c_pid, _ in self.clients:
                        if c_addr[0] == addr[0] and c_addr[1] == addr[1]:
                            pid = c_pid
                            break
                if pid is not None:
                    self.last_seen[pid] = time.time()
                    self.input_queue.put((pid, packet.get("data", {})))

            elif ptype == "disconnect":
                pid = None
                with self.clients_lock:
                    for i, (c_addr, c_pid, c_name) in enumerate(self.clients):
                        if c_addr[0] == addr[0] and c_addr[1] == addr[1]:
                            pid = c_pid
                            name = c_name
                            self.clients.pop(i)
                            break
                if pid is not None:
                    self.last_seen.pop(pid, None)
                    self.lobby_updates.put(("player_left", pid, name))

    # ── UDP send ───────────────────────────────────────────────

    def _send_state(self):
        state = None
        while True:
            try:
                state = self.state_queue.get_nowait()
            except queue.Empty:
                break
        if state is None:
            return
        data = pickle.dumps(state)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def _send_outgoing(self):
        try:
            packet = self.outgoing_queue.get_nowait()
        except queue.Empty:
            return
        data = pickle.dumps(packet)
        with self.clients_lock:
            for c_addr, _, _ in self.clients:
                try:
                    self.udp_socket.sendto(data, c_addr)
                except OSError:
                    pass

    def send_to_all(self, packet):
        self.outgoing_queue.put(packet)

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
                self.lobby_updates.put(("player_left", pid, name))

    def get_lobby_players(self):
        result = [(self.host_name, 0)]
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
    """Client-side networking (runs on remote machines)"""
    def __init__(self):
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setblocking(False)
        self.server_addr = None
        self.player_id = -1
        self.latest_state = None
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
                    try:
                        resp = pickle.loads(sock.recv(size))
                    except Exception:
                        sock.close()
                        return False
                    if resp.get("type") == "accept":
                        self.player_id = resp["player_id"]
                        self.server_addr = (host, port)
                        self.connected = True
                        sock.close()
                        # Register UDP connection
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
        packet = {"type": "pos_update", "data": input_data}
        try:
            self.udp_socket.sendto(pickle.dumps(packet), self.server_addr)
        except OSError:
            pass

    def send(self, packet):
        if not self.server_addr:
            return
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
        self.latest_state = None
        try:
            self.udp_socket.close()
        except OSError:
            pass
