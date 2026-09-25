"""JSON conversation format."""

import json as _json

NAME = "json"
DESCRIPTION = "Structured JSON object"
EXT = ".json"


def format_conversation(events, metadata):
    output = {
        "metadata": metadata,
        "conversation": events,
    }
    return _json.dumps(output, indent=2) + "\n"
