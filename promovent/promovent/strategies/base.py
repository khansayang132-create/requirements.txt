from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Strategy:
    name: str = "base"
    params: dict = field(default_factory=dict)
    # Documentation contract (shown in the API and Quant Lab)
    entry_rules: str = ""
    exit_rules: str = ""
    stop_method: str = ""
    failure_conditions: str = ""
    suited_regimes: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return DataFrame indexed like df with columns side, stop, target, reason."""
        raise NotImplementedError

    @staticmethod
    def _empty(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"side": np.zeros(len(df), int), "stop": np.nan, "target": np.nan, "reason": ""},
                            index=df.index)

    def describe(self) -> dict:
        return {"name": self.name, "params": self.params, "entry_rules": self.entry_rules,
                "exit_rules": self.exit_rules, "stop_method": self.stop_method,
                "failure_conditions": self.failure_conditions, "suited_regimes": list(self.suited_regimes),
                "timeframes": list(self.timeframes)}
