from __future__ import annotations

import re

_CLAUSE = re.compile(
    r"(مبلغ\s*)([\d,،/]+)(\s*میلیارد\s*ریال\s*منقسم\s*به\s*)([\d,،/]+)(\s*سهم\s*با\s*نام\s*)([\d,،/]+)(\s*ریالی)"
)


def reconcile_capital_shares(text: str, corrections: list[dict]) -> str:
    def check(m: re.Match) -> str:
        raw_cap, raw_shares, raw_par = m.group(2), m.group(4), m.group(6)
        cap, shares, par = (re.sub(r"\D", "", v) for v in (raw_cap, raw_shares, raw_par))
        if not (cap and shares and par):
            return m.group(0)
        cap_val, shares_val, par_val = int(cap), int(shares), int(par)

        def shares_for(par_value: int) -> int:
            return (cap_val * 1_000_000_000) // max(1, par_value)

        if par_val == 10000 and shares_val != shares_for(10000) and shares_val == shares_for(1000):
            corrections.append({
                "kind": "accounting_identity",
                "input": f"par={raw_par}",
                "output": "par=1,000",
                "status": "auto_corrected",
            })
            par_val = 1000
            raw_par = "1,000"

        expected = shares_for(par_val)
        if shares_val != expected and str(shares_val)[:3] == str(expected)[:3]:
            corrections.append({
                "kind": "accounting_identity",
                "input": f"cap={raw_cap}, shares={raw_shares}, par={raw_par}",
                "output": f"shares={expected:,}",
                "status": "auto_corrected",
            })
            raw_shares = f"{expected:,}"
        return f"{m.group(1)}{raw_cap}{m.group(3)}{raw_shares}{m.group(5)}{raw_par}{m.group(7)}"

    return _CLAUSE.sub(check, text)
