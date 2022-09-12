import json
import typing

__all__ = ["APIMessageTX", "APIMessageRX"]

from multidict import MultiDictProxy


class APIMessageTX:

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __str__(self):
        """Dump the api content to json"""
        return json.dumps(self.kwargs, indent=4)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding) + b"\n\r"


class APIMessageRX:

    def __init__(self, json_raw: typing.Union[str, bytes, MultiDictProxy]):
        """Load the api content from bytes"""
        is_json = False

        if isinstance(json_raw, str) or isinstance(json_raw, bytes):
            is_json = True

        if isinstance(json_raw, bytes):
            json_raw = json_raw.decode('utf-8')
        elif isinstance(json_raw, MultiDictProxy):
            new_dict = {}
            # Search through the multidict for and values with 'true' or 'false' and convert them to bool
            for key, value in json_raw.items():
                if value == 'true':
                    new_dict[key] = True
                elif value == 'false':
                    new_dict[key] = False
                else:
                    new_dict[key] = value
            self.__dict__.update(new_dict)
        if is_json:
            try:
                self.__dict__.update(json.loads(json_raw))  # Load the json into the locals()
            except json.JSONDecodeError as e:
                print(f"RX error: {e}")
                self.error = e

    def __str__(self):
        """Dump the api content to json"""
        return json.dumps(self.__dict__)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding)
