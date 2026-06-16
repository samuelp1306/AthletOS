"""Prospektive Validierung: schlaegt der Adjusted Score den rohen Recovery-Wert?

Liest daily_validation und korreliert beide Scores gegen die blinde
perceived_readiness (1-10). Williams-Test prueft, ob der Vorsprung echt ist.
Beide Scores sind 'hoeher = besser' -> erwartete Korrelation POSITIV.
"""

import sqlite3
import math
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from scipy.stats import t as t_dist


def validate_scores(db_path: str, min_n: int = 14) -> dict:
    cols = ["date", "perceived_readiness", "raw_recovery", "adjusted_readiness"]
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(f"SELECT {', '.join(cols)} FROM daily_validation", conn)

    df = df.dropna(subset=cols[1:])
    n = len(df)
    if n < min_n:
        return {"n": n,
                "verdict": f"Nur {n} valide Tage. Unter {min_n} sage ich nichts "
                           "— das waere Rauschen, kein Ergebnis."}

    pr = df["perceived_readiness"]
    raw = df["raw_recovery"]
    adj = df["adjusted_readiness"]

    rs_raw = spearmanr(pr, raw)[0]
    rs_adj = spearmanr(pr, adj)[0]

    r12 = pearsonr(pr, raw)[0]
    r13 = pearsonr(pr, adj)[0]
    r23 = pearsonr(raw, adj)[0]

    R = 1 - r12**2 - r13**2 - r23**2 + 2 * r12 * r13 * r23
    df_t = n - 3
    denom = math.sqrt(2 * ((n - 1) / df_t) * R
                      + ((r12 + r13) ** 2 / 4) * (1 - r23) ** 3)
    if denom == 0:
        return {"n": n, "verdict": "Raw und Adjusted sind quasi identisch — "
                                   "nichts zu vergleichen."}
    t_stat = (r13 - r12) * math.sqrt((n - 1) * (1 + r23)) / denom
    p_better = 1 - t_dist.cdf(t_stat, df_t)

    better, sig = rs_adj > rs_raw, p_better < 0.05
    if sig and better:
        verdict = (f"Adjusted schlaegt Raw signifikant (p={p_better:.3f}). "
                   "Beleg — kein Beweis bei n=1, aber zitierbar.")
    elif better:
        verdict = (f"Adjusted liegt vorn, aber nicht signifikant (p={p_better:.3f}). "
                   "Noch KEINE 'besser'-Behauptung posten. Weiter loggen.")
    else:
        verdict = ("Raw ist gleich gut oder besser. Deine Anpassung bringt aktuell "
                   "nichts Messbares — unbequem, aber das ist die ehrliche Antwort.")

    print(f"\n  Validierung  (n = {n} Tage)")
    print(f"  {'-'*44}")
    print(f"  Raw recovery   vs. gefuehlt : rho = {rs_raw:+.3f}")
    print(f"  Adjusted score vs. gefuehlt : rho = {rs_adj:+.3f}")
    print(f"  Delta (adj - raw)           : {rs_adj - rs_raw:+.3f}")
    print(f"  Williams p (adj > raw)      : {p_better:.4f}")
    print(f"  {'-'*44}")
    print(f"  -> {verdict}\n")

    return {"n": n, "spearman_raw": round(rs_raw, 3),
            "spearman_adjusted": round(rs_adj, 3),
            "delta": round(rs_adj - rs_raw, 3),
            "p_adjusted_better": round(p_better, 4), "verdict": verdict}
