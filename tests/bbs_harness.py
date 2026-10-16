"""Run the real Aether BBS, headless, on one local test instance.

For tests/test_local_test_bbs.py: started in a separate Python with the
Aether BBS checkout on its path (it has a ``vara`` package of its own).

    python -I bbs_harness.py <bbs_dir> <cmd_port> <data_port> <work_dir>
                             [<user_call> <password>]

Builds what the BBS's main.py builds for sessions — message store,
access control, the modem instance manager and the session dispatcher —
with one instance set up as the local test help says (Transport VARA FM,
Host 127.0.0.1, the given ports, Auto Start off).  With a user and
password the user is approved and has that password, so the BBS logs
them in with its HMAC challenge.  Prints "STATE <name> WRONG=<n>" when
the instance's modem state settles, then serves until stdin closes.
BBS log lines go to stderr.
"""

import logging
import sys
import time
from pathlib import Path

bbs_dir, cmd_port, data_port, work = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
user = sys.argv[5] if len(sys.argv) > 6 else ""
password = sys.argv[6] if len(sys.argv) > 6 else ""
sys.path.insert(0, bbs_dir)

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(name)s %(levelname)s %(message)s")

from core.config import AppConfig, InstanceConfig        # noqa: E402
from core.events import EventBus                          # noqa: E402
from bbs.store import MessageStore                        # noqa: E402
from bbs.access import AccessController, Role             # noqa: E402
from bbs.dispatcher import SessionDispatcher              # noqa: E402
from vara.instance_manager import ModemInstanceManager    # noqa: E402

cfg = AppConfig()
cfg.station.bbs_callsign = "N0BBS-10"
cfg.station.sysop_callsign = "N0SYS"
cfg.bbs.message_dir = str(work / "messages")
cfg.instances = [InstanceConfig(
    name="Local test", transport="VARA_FM", host="127.0.0.1",
    cmd_port=cmd_port, data_port=data_port, auto_start=False)]

bus = EventBus()
store = MessageStore(cfg, event_bus=bus)
store.initialize()
access = AccessController(conn=store.conn, lock=store.lock, config=cfg, event_bus=bus)
if user:
    access.set_role(user, Role.APPROVED, changed_by="TEST")
    access.set_password(user, password)

im = ModemInstanceManager(cfg, bus)
dispatcher = SessionDispatcher(cfg, im, store, bus, access_controller=access)
im.start_all()
dispatcher.start()

mux = im.all_muxes()["Local test"]
deadline = time.time() + 30
while time.time() < deadline and mux.state.name != "LISTENING":
    time.sleep(0.1)
wrong = mux._interface._init_wrong_count
print(f"STATE {mux.state.name} WRONG={wrong}", flush=True)

sys.stdin.read()          # until the test is done
dispatcher.stop()
im.stop_all()
