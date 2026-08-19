import unittest
from anton.governor import (AUTO_EXECUTE, LEARN_FIRST, PRESENT_FOR_APPROVAL,
                             PRESENT_WITH_EVIDENCE, classify, score)


class TestGovernor(unittest.TestCase):
    def test_score(self):
        self.assertEqual(score(0.8, 0.9), 0.72)

    def test_auto_execute_when_high_and_low_risk(self):
        r = classify(0.9, 0.9, risk="low", kind="internal")
        self.assertEqual(r.route, AUTO_EXECUTE)
        self.assertEqual(r.score, 0.81)

    def test_money_always_approval(self):
        r = classify(0.99, 0.99, risk="low", kind="money")
        self.assertEqual(r.route, PRESENT_FOR_APPROVAL)

    def test_outbound_always_approval(self):
        r = classify(0.8, 0.8, risk="low", kind="outbound")
        self.assertEqual(r.route, PRESENT_FOR_APPROVAL)

    def test_low_feasibility_learns_first(self):
        r = classify(0.8, 0.2, risk="low")
        self.assertEqual(r.route, LEARN_FIRST)

    def test_uncertain_presents_with_evidence(self):
        r = classify(0.5, 0.5, risk="low")
        self.assertEqual(r.route, PRESENT_WITH_EVIDENCE)

    def test_score_edge_cases(self):
        self.assertEqual(score(-1.0, 0.5), 0.0)
        self.assertEqual(score(0.5, -0.5), 0.0)
        self.assertEqual(score(float("nan"), 0.5), 0.0)
        self.assertEqual(score(0.5, float("nan")), 0.0)
        self.assertEqual(score(float("inf"), 0.5), 0.0)

