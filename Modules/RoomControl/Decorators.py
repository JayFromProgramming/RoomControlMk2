import functools


# Create a decorator for an @property method to indicate if it is allowed to be called by the API
def api_action(func):
    @functools.wraps(func)
    def wrapper_api_action(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper_api_action.api_action = True
    return wrapper_api_action
