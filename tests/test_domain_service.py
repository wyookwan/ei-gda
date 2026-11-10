import unittest
from services.domain_service import list_packs, get_pack, evidence_review

class TestDomainPacks(unittest.TestCase):
    def test_pack_validation(self):
        self.assertEqual(len(list_packs()), 5)
        self.assertIsNone(get_pack('../secrets'))
        for pack in list_packs():
            self.assertTrue(pack['controls'])
            self.assertEqual(len({x['id'] for x in pack['controls']}), len(pack['controls']))

    def test_manual_evidence_coverage(self):
        pack = get_pack('justice')
        self.assertEqual(evidence_review(pack, {})['coverage_percent'], 0)
        scores = {c['id']:'evidenced' for c in pack['controls']}
        self.assertEqual(evidence_review(pack, scores)['coverage_percent'], 100)
        self.assertFalse(evidence_review(pack, scores)['critical_open'])
        with self.assertRaises(ValueError):
            evidence_review(pack, {'JUS-01':'invalid'})

if __name__ == '__main__': unittest.main()
