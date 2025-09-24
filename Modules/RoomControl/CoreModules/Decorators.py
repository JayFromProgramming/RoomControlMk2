import functools
from threading import Thread
# from loguru import logger as logging


# def get_api_actions(obj):
#     """Get all methods of an object that have the api_action attribute"""
#     try:
#         actions = {}
#         attributes = dir(obj)
#         methods = [getattr(obj, name) for name in attributes if callable(getattr(obj, name))]
#         for method in methods:
#             if hasattr(method, "api_action"):
#                 actions[method.__name__] = method
#         return actions
#     except Exception as e:
#         logging.error(f"get_api_actions: {e}")
#         return {}
#
#
# # Create a decorator for a @property method to indicate if it is allowed to be called by the API
# def api_action(func):
#
#     @functools.wraps(func)  # Preserve the original function's name and docstring
#     def wrapper_api_action(*args, **kwargs):
#         return func(*args, **kwargs)
#
#     wrapper_api_action.api_action = True
#     # wrapper_api_action.api_name = name if name else func.__name__
#     return wrapper_api_action


def background(func):
    """Decorator to automatically launch a function in a thread"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # replaces original function...
        # ...and launches the original in a thread
        thread = Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    return wrapper
