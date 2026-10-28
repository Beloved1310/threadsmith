"""Which Agent Engine this process runs as, if any.

On Agent Runtime, agents-cli sets APP_URL to the engine's passthrough URL:
  https://<loc>-aiplatform.googleapis.com/reasoningEngines/v1/
  projects/<project>/locations/<loc>/reasoningEngines/<id>/api
Locally there is no APP_URL, so this returns None.
"""

import os
import re
from typing import NamedTuple, Optional

_ENGINE_RE = re.compile(r"projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)")


class AgentEngine(NamedTuple):
    project: str
    location: str
    engine_id: str


def agent_engine() -> Optional[AgentEngine]:
    match = _ENGINE_RE.search(os.environ.get("APP_URL", ""))
    return AgentEngine(*match.groups()) if match else None
