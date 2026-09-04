"""Pattern Memory — Data Models"""
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional
import uuid


@dataclass
class Pattern:
    """A learned behavioral pattern."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trigger: str = ""          # When to apply this pattern
    action: str = ""           # What the agent should do
    category: str = "general"  # code_style, threshold, tool_choice, workflow, exclusion
    confidence: float = 0.3    # 0.0 to 1.0
    use_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: Optional[datetime] = None
    last_confirmed: Optional[datetime] = None
    # Auto-confirmation tracking
    applied_count: int = 0     # Times pattern was applied (retrieved via check_before_acting)
    last_applied: Optional[datetime] = None  # When pattern was last applied
    auto_confirmed: bool = False  # Whether pattern was auto-confirmed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "action": self.action,
            "category": self.category,
            "confidence": self.confidence,
            "use_count": self.use_count,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "last_confirmed": self.last_confirmed.isoformat() if self.last_confirmed else None,
            "applied_count": self.applied_count,
            "last_applied": self.last_applied.isoformat() if self.last_applied else None,
            "auto_confirmed": self.auto_confirmed,
        }


@dataclass
class Correction:
    """A recorded user correction."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_behavior: str = ""   # What the agent did wrong
    corrected_behavior: str = ""  # What the user wanted instead
    context: str = ""             # What was happening
    category: str = "general"
    pattern_id: Optional[str] = None  # Links to learned pattern (if any)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_behavior": self.original_behavior,
            "corrected_behavior": self.corrected_behavior,
            "context": self.context,
            "category": self.category,
            "pattern_id": self.pattern_id,
            "timestamp": self.timestamp.isoformat(),
        }
