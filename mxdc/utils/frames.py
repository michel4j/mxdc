import os
import time
from queue import Queue

from mxdc import Engine
from mxdc.libs.imageio import read_image

MAX_FILE_FREQUENCY = 10


class DataMonitor(Engine):
    """
    A detector helper engine which loads frames and emits them to watchers as they are being acquired.

    :param master: Master object to which new data should be added. Must implement the
        process_frame(data) method.
    """

    def __init__(self, master):
        super().__init__()
        self.master = master


class FileMonitor(DataMonitor):
    """
    Data Monitor which reads frames from disk
    """

    MAX_SAVE_JITTER = 0.5  # maxium amount of time in seconds to wait for tile to be done writing to disk

    def __init__(self, *args):
        super().__init__(*args)
        self.skip_count = 10  # number of frames to skip at once
        self.inbox = Queue(10000)
        self.start()

    def add(self, path):
        self.inbox.put(path)

    def load(self, path):
        self.set_state(busy=True)
        attempts = 0
        success = False
        while not success and attempts < 10:
            loadable = (
                    os.path.exists(path) and
                    time.time() - os.path.getmtime(path) > self.MAX_SAVE_JITTER
            )
            if loadable:
                try:
                    dataset = read_image(path)
                    self.master.process_frame(dataset)
                    success = True
                except Exception:
                    success = False
            attempts += 1
            time.sleep(0.1)
        self.set_state(busy=False)
        return success

    def run(self):
        path = None
        while not self.stopped:
            # Load frame if path exists
            count = 0
            while not self.inbox.empty() and count < self.skip_count:
                path = self.inbox.get()
                count += 1

            if path and not self.get_state("busy"):
                success = self.load(path)
                if success:
                    path = None
            time.sleep(1/MAX_FILE_FREQUENCY)


class StreamMonitor(DataMonitor):
    """
    A data monitor which monitors a stream for new data
    """
