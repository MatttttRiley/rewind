#!/usr/bin/env python3
"""Rewind launcher - starts the background recorder and opens the viewer.

Run this. It spawns the recorder in a background thread and opens the
timeline window. Close the window to stop the viewer; the recorder keeps
running until you choose Quit from the tray (or close this console).
"""

import threading
import sys

import common
import recorder


def main():
    # make sure DB exists
    common.connect().close()

    stop = threading.Event()
    t = threading.Thread(target=recorder.run, kwargs={"stop_event": stop},
                         daemon=True)
    t.start()

    try:
        import viewer
        viewer.main()
    finally:
        stop.set()

    # tray icon (best effort; viewer closing ends the session)
    print("[rewind] bye", flush=True)


if __name__ == "__main__":
    main()
