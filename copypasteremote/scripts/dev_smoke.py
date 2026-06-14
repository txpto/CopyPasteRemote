"""Developer smoke test: drive two agents through a live server using real
client config files. Not part of the pytest suite; handy for manual verification.

Usage (with a server already running and two client configs generated):
    python scripts/dev_smoke.py <casa.json> <oficina.json>
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cpr_client.agent import Agent, ClipboardBackend
from cpr_client.clipdata import ClipData
from cpr_client.config import ClientConfig


class FakeClipboard(ClipboardBackend):
    def __init__(self):
        self.clip = None

    def read(self):
        return self.clip

    def write(self, clip):
        self.clip = clip


def main():
    cfg1 = ClientConfig.load(sys.argv[1])  # machine 1 (PC-Casa, slot 1)
    cfg2 = ClientConfig.load(sys.argv[2])  # machine 2 (PC-Oficina, slot 2)

    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1, a2 = Agent(cfg1, cb1), Agent(cfg2, cb2)

    print("server info:", a1.check_server().get("version"))

    # 1) TEXT: machine 1 -> mailbox 2
    cb1.clip = ClipData.text_data("Hola desde PC-Casa → portapapeles de PC-Oficina ✅")
    env = a1.push(cfg2.machine_id)
    print("pushed:", env.human_summary(), "inline=" + str(env.inline))
    a2.pull(cfg2.machine_id)
    assert cb2.clip.text == "Hola desde PC-Casa → portapapeles de PC-Oficina ✅"
    print("TEXT roundtrip OK ->", repr(cb2.clip.text))

    # 2) FILES: a folder with a file, machine 1 -> mailbox 2
    src = tempfile.mkdtemp(prefix="cpr_smoke_src_")
    os.makedirs(os.path.join(src, "proyecto", "sub"))
    with open(os.path.join(src, "proyecto", "nota.txt"), "w", encoding="utf-8") as fh:
        fh.write("contenido de la nota")
    with open(os.path.join(src, "proyecto", "sub", "datos.bin"), "wb") as fh:
        fh.write(os.urandom(2048))

    cb1.clip = ClipData.files_data([os.path.join(src, "proyecto")])
    env = a1.push(cfg2.machine_id)
    print("pushed:", env.human_summary(), "blob=" + str(env.blob_id is not None))
    a2.pull(cfg2.machine_id)
    out = cb2.clip.paths[0]
    assert os.path.isdir(out)
    with open(os.path.join(out, "nota.txt"), encoding="utf-8") as fh:
        assert fh.read() == "contenido de la nota"
    print("FILES roundtrip OK -> extracted folder at", out)

    a1.close()
    a2.close()
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
