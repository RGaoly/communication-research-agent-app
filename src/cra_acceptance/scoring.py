"""Deterministic expert-score aggregation; does not supply expert judgments."""
import math
from cra_engine.common import require


def literature_score(cases):
    require(isinstance(cases,list) and cases, "Expert-rated cases required")
    correct, severe, disagreements = 0, 0, 0
    for case in cases:
        ratings = case.get("expert_ratings", [])
        require(len(ratings) == 2 and len({r.get("reviewer") for r in ratings}) == 2 and all(r.get("reviewer") for r in ratings), "Two distinct expert ratings required for every case")
        labels = {"supported", "unsupported", "insufficient"}
        require(all(r.get("support") in labels and len(r.get("note", "")) >= 8 for r in ratings), "Expert labels and rationale required")
        gold = case.get("adjudicated_support")
        require(gold in labels and case.get("predicted_support") in labels, "Model and adjudicated labels required")
        if ratings[0]["support"] != ratings[1]["support"]:
            disagreements += 1
            require(bool(case.get("adjudicator")) and len(case.get("adjudication_note", "")) >= 8, "Disagreement requires explicit adjudication")
        else:
            require(gold == ratings[0]["support"], "Consensus/adjudicated label conflict")
        same = case["predicted_support"] == gold
        correct += same
        severe += case.get("core_claim") is True and case["predicted_support"] == "supported" and gold != "supported"
    n = len(cases); rate = correct/n; z = 1.959963984540054
    denominator = 1+z*z/n; centre = (rate+z*z/(2*n))/denominator
    half = z*math.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/denominator
    return {"n":n,"correct":correct,"accuracy":rate,"wilson_95":[centre-half,centre+half],"disagreements":disagreements,"severe_core_misquotes":severe,"passed":n>=100 and rate>=.95 and severe==0}
