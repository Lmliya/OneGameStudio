"""机械门禁入口。"""

from backend.gate.mechanical import GateUnavailableError, run_mechanical_gate

__all__ = ["run_mechanical_gate", "GateUnavailableError"]
