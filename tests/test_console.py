"""Integração HTTP + RCON simulado. Execute: python3 -m unittest discover -s tests -v

Requer PHP 8.3+ no PATH ou PHP_BINARY apontando para o executável.
Não acessa seu Minecraft, mundo, backups nem Docker.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request


def read_exact(stream, length):
    data = b""
    while len(data) < length:
        chunk = stream.recv(length - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


class FakeRcon(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    reject_auth = False
    commands = []


class RconHandler(socketserver.BaseRequestHandler):
    def send(self, request_id, packet_type, text):
        raw = struct.pack("<ii", request_id, packet_type) + text.encode() + b"\0\0"
        self.request.sendall(struct.pack("<i", len(raw)) + raw)

    def handle(self):
        try:
            while True:
                length = struct.unpack("<i", read_exact(self.request, 4))[0]
                raw = read_exact(self.request, length)
                request_id, packet_type = struct.unpack("<ii", raw[:8])
                text = raw[8:-2].decode()
                if packet_type == 3:
                    ok = text == "test-rcon-password" and not self.server.reject_auth
                    self.send(request_id if ok else -1, 2, "")
                elif packet_type == 2:
                    self.server.commands.append(text)
                    if text == "help":
                        # Fragmentação de respostas e mensagens maiores que um pacote.
                        self.send(request_id, 0, "A" * 4096)
                        self.send(request_id, 0, "B" * 4096)
                    elif text == "list":
                        self.send(request_id, 0, "There are 2 of 10 players online: Mahal, Marvingames")
                    elif text == "empty":
                        self.send(request_id, 0, "")
                    elif text == "unsafe":
                        self.send(request_id, 0, '<img src=x onerror="alert(1)">')
                    else:
                        self.send(request_id, 0, "Executado: " + text)
                else:
                    self.send(request_id, 0, "Unknown request")
        except (EOFError, ConnectionError):
            return


class ConsoleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        php = os.environ.get("PHP_BINARY") or shutil.which("php")
        if not php:
            raise unittest.SkipTest("Instale PHP 8.3+ ou configure PHP_BINARY.")
        cls.rcon = FakeRcon(("127.0.0.1", 0), RconHandler)
        cls.rcon.commands = []
        threading.Thread(target=cls.rcon.serve_forever, daemon=True).start()
        cls.temp = tempfile.TemporaryDirectory()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}/"
        env = dict(os.environ, PANEL_PASSWORD="test-panel-password-1234",
                   MC_RCON_PASSWORD="test-rcon-password", MC_RCON_HOST="127.0.0.1",
                   MC_RCON_PORT=str(cls.rcon.server_address[1]))
        root = Path(__file__).resolve().parents[1] / "minecraft-painel/panel"
        cls.log = open(Path(cls.temp.name) / "php.log", "w")
        cls.php = subprocess.Popen([php, "-n", "-d", f"session.save_path={cls.temp.name}",
                                    "-S", f"127.0.0.1:{port}", "-t", str(root)],
                                   env=env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url, timeout=.2).close()
                return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(.05)
        cls.tearDownClass()
        raise RuntimeError("PHP não iniciou.")

    @classmethod
    def tearDownClass(cls):
        cls.php.terminate()
        cls.php.wait(timeout=5)
        cls.rcon.shutdown()
        cls.rcon.server_close()
        cls.log.close()
        cls.temp.cleanup()

    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.token = self.csrf(self.request()[1])
        _, page = self.request({"action": "login", "csrf": self.token,
                                "password": "test-panel-password-1234"})
        self.token = self.csrf(page)

    def request(self, fields=None):
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None
        try:
            response = self.client.open(self.url, data, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    @staticmethod
    def csrf(page):
        return re.search(r'name="csrf" value="([a-f0-9]+)"', page)[1]

    def command(self, command, **extra):
        return self.request(dict(action="command", format="json", csrf=self.token,
                                 command=command, **extra))

    def test_authentication_and_csrf(self):
        before = len(self.rcon.commands)
        status, data = self.request({"action": "command", "format": "json",
                                     "command": "list", "csrf": "wrong"})
        self.assertEqual(status, 403)
        self.assertIn("CSRF", json.loads(data)["error"])
        self.assertEqual(len(self.rcon.commands), before)
        self.request({"action": "logout", "csrf": self.token})
        before = len(self.rcon.commands)
        status, data = self.command("list")
        self.assertEqual(status, 401)
        self.assertIn("login", json.loads(data)["error"])
        self.assertEqual(len(self.rcon.commands), before)

    def test_command_and_persistent_history(self):
        status, data = self.command("/weather clear")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["command"], "weather clear")
        self.assertIn("Executado: weather clear", json.loads(data)["response"])
        self.assertIn("Executado: weather clear", self.request()[1])

    def test_input_validation(self):
        before = len(self.rcon.commands)
        for command in ["", "/", "a" * 257, "list\nstop", "list\0", "\nlist", "list\x7f"]:
            status, _ = self.command(command)
            self.assertEqual(status, 422, repr(command))
        self.assertEqual(len(self.rcon.commands), before)

    def test_multipart_and_empty_response(self):
        status, data = self.command("help")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["response"], "A" * 4096 + "B" * 4096)
        status, data = self.command("empty")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["response"], "(Sem mensagem de retorno)")

    def test_history_escaping_and_limit(self):
        self.command("unsafe")
        page = self.request()[1]
        self.assertNotIn('<img src=x onerror="alert(1)">', page)
        self.assertIn("&lt;img", page)
        for index in range(51):
            self.command(f"say {index}")
        page = self.request()[1]
        self.assertEqual(page.count('data-command-text="'), 50)
        self.assertNotIn('data-command-text="say 0"', page)
        self.assertIn('data-command-text="say 50"', page)

    def test_rcon_auth_failure(self):
        self.rcon.reject_auth = True
        try:
            status, data = self.command("list")
            self.assertEqual(status, 502)
            self.assertIn("Senha RCON incorreta", json.loads(data)["error"])
            self.assertNotIn("test-rcon-password", data)
        finally:
            self.rcon.reject_auth = False

    def test_html_fallback(self):
        status, page = self.request({"action": "command", "csrf": self.token,
                                     "command": "time set day"})
        self.assertEqual(status, 200)
        self.assertIn("Executado: time set day", page)


if __name__ == "__main__":
    unittest.main()
