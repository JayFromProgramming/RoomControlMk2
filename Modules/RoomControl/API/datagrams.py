import json
import typing

__all__ = ["APIMessageTX", "APIMessageRX"]

from json import JSONDecodeError

from multidict import MultiDictProxy
from loguru import logger as logging


class APIMessageTX:

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def _clean(self, value):
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._clean(v) for v in value]
        else:
            try:
                json.dumps(value)
                return value
            except (TypeError, OverflowError):
                return str(type(value))

    def __str__(self):
        """Dump the api content to json"""
        # Remove all values that aren't JSON serializable
        try:
            return json.dumps(self.kwargs, indent=4)
        except TypeError:
            self.kwargs = self._clean(self.kwargs)
            return json.dumps(self.kwargs, indent=4)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding) + b"\n\r"


class APIMessageRX:

    def __init__(self, json_raw: typing.Union[str, bytes, bytearray, dict, MultiDictProxy]):
        """Load the api content from bytes"""

        if isinstance(json_raw, bytes) or isinstance(json_raw, bytearray):
            json_raw = json_raw.decode('utf-8')
            try:
                self.__dict__.update(json.loads(json_raw))  # Load the json into the locals()
            except json.JSONDecodeError as e:
                logging.error(f"RX error: {e}")
                logging.exception(e)
                self.error = e
        elif isinstance(json_raw, str):
            try:
                self.__dict__.update(json.loads(json_raw))  # Load the json into the locals()
            except json.JSONDecodeError as e:
                logging.error(f"RX error: {e}")
                logging.exception(e)
                self.error = e
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
        elif isinstance(json_raw, dict):
            self.__dict__.update(json_raw)
        else:
            self.error = f"Invalid JSON datagram type: {type(json_raw)}"

    def __str__(self):
        """Dump the api content to json"""

        values = {}
        # Remove all values that aren't JSON serializable
        for key, value in self.__dict__.items():
            try:
                json.dumps(value)
                values[key] = value
            except TypeError as e:
                logging.error(f"TX error: {e}")
                logging.exception(e)
                pass
        return json.dumps(values)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding)
