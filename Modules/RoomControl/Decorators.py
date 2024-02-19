import functools
from threading import Thread

# Create a decorator for an @property method to indicate if it is allowed to be called by the API
def api_action(func):
    @functools.wraps(func)
    def wrapper_api_action(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper_api_action.api_action = True
    return wrapper_api_action


def background(func):
    """Decorator to automatically launch a function in a thread"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # replaces original function...
        # ...and launches the original in a thread
        thread = Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    return wrapper