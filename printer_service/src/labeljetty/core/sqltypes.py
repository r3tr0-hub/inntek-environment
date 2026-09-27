from typing import Any, Optional
from sqlalchemy.types import TypeDecorator, Text
import json


class SqlJsonText(TypeDecorator):
    """Stores JSON-serializable Python objects (dicts or Pydantic models) as TEXT.

    Pydantic models are dumped via ``model_dump()`` before serialization; ``None``
    is stored as SQL NULL and read back as ``None``.
    """

    impl = Text

    def process_bind_param(self, value: Any, dialect) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        return json.dumps(value)

    def process_result_value(self, value: Optional[str], dialect) -> Any:
        if value is None:
            return None
        return json.loads(value)
