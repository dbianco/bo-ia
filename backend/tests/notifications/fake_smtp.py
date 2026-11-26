"""A small SMTP server for the tests: it keeps what it accepts, and can fail on purpose."""
from __future__ import annotations

import email
import socketserver
import threading
from email import policy
from email.message import EmailMessage


class FakeSMTP:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.recipients: list[str] = []
        self.replies: dict[str, str] = {}  # command -> reply, instead of the normal one
        self.reject: dict[str, str] = {}  # recipient -> reply to RCPT
        self.drop_after_accepting = False  # close without answering, having kept the message
        self.connections = 0
        self._server: socketserver.ThreadingTCPServer | None = None
        self.port = 0

    def start(self) -> None:
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def _say(self, line: str) -> None:
                self.wfile.write(line.encode() + b"\r\n")

            def handle(self) -> None:
                outer.connections += 1
                self._say(outer.replies.get("CONNECT", "220 fake"))
                recipients: list[str] = []
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    line = raw.decode().strip()
                    verb = line.split(":")[0].split(" ")[0].upper()
                    if verb in outer.replies:
                        self._say(outer.replies[verb])
                    elif verb == "EHLO":
                        self._say("250-fake")
                        self._say("250 8BITMIME")
                    elif verb == "RCPT":
                        address = line.split("<")[1].split(">")[0]
                        self._say(outer.reject.get(address, "250 ok"))
                        recipients.append(address)
                    elif verb == "DATA":
                        self._say("354 go on")
                        body = b""
                        while not body.endswith(b"\r\n.\r\n"):
                            body += self.rfile.readline()
                        if "END" in outer.replies:
                            self._say(outer.replies["END"])
                            continue
                        text = body[:-5].replace(b"\r\n..", b"\r\n.")
                        outer.messages.append(email.message_from_bytes(text, policy=policy.default))
                        outer.recipients += recipients
                        if outer.drop_after_accepting:
                            self.connection.close()
                            return
                        self._say("250 accepted")
                    elif verb == "QUIT":
                        self._say("221 bye")
                        return
                    else:
                        self._say("250 ok")

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, args=(0.02,), daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def text(self, i: int = -1) -> str:
        return self.messages[i].get_body(("plain",)).get_content()

    def html(self, i: int = -1) -> str:
        return self.messages[i].get_body(("html",)).get_content()
