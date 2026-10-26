"""Keep UI execution responsive while a bounded local generation runs."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as WaitTimeout
from threading import BoundedSemaphore, Event

from src.ui.service import StudioServiceError

_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='local-commentary')
_capacity = BoundedSemaphore(2)


def generate_interactively(service, episode, *, progress, **selection):
    if not _capacity.acquire(blocking=False):
        raise StudioServiceError('The studio is busy right now. Please wait a moment and try again.')
    cancel = Event()

    def work():
        try:
            return service.broadcast(episode, cancel_event=cancel, **selection)
        finally:
            _capacity.release()

    try:
        future = _workers.submit(work)
    except BaseException:
        _capacity.release()
        raise
    try:
        while True:
            try:
                return future.result(timeout=.1)
            except WaitTimeout:
                # A Streamlit update yields to rerun/disconnect requests. Interruption
                # signals the network owner to cancel without starting another call.
                progress()
    except BaseException:
        cancel.set()
        raise
