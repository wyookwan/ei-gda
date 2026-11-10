import unittest
from unittest.mock import patch
import test_international_catalog as fixtures
from extensions import db
from models import DocumentCheck

class ProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.CatalogTests.setUp(self)
        # Pilot: model use is default-deny; every migrated database has these explicit rules (seeded by sync_catalog).
        from services.model_gate import seed_default_rules
        seed_default_rules(db.session)
        db.session.commit()
    tearDown=fixtures.CatalogTests.tearDown

    def test_classification_routes_and_failures(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=1,role='user')
        check=DocumentCheck.query.first()
        result={'all_items':[], 'per_standard':[], 'overall_percent':0,'maturity_level':'Initial'}
        with patch('app.gemini_enabled',return_value=True), patch('app.local_model_enabled',return_value=True), patch('app.score_with_gemini') as gemini, patch('app.score_with_local_model') as local, patch('app.run_hybrid_compliance',return_value=result) as hybrid, patch('app.generate_system_report'):
            for classification,provider in [('open','gemini'),('confidential','local_model')]:
                for fail in [False,True]:
                    gemini.reset_mock();local.reset_mock();hybrid.reset_mock()
                    gemini.return_value=local.return_value={'used':not fail,'error':'test error'}
                    check.data_classification=classification;db.session.commit()
                    self.assertEqual(client.post(f'/check/{check.id}/run-compliance').status_code,302)
                    (gemini if classification=='open' else local).assert_called_once()
                    (local if classification=='open' else gemini).assert_not_called()
                    self.assertEqual(check.processing_provider,provider+('_error' if fail else ''))
                    if fail:hybrid.assert_not_called()
            check.data_classification='invalid';db.session.commit();gemini.reset_mock();local.reset_mock()
            client.post(f'/check/{check.id}/run-compliance')
            gemini.assert_not_called();local.assert_not_called()

    def test_missing_gemini_config_does_not_use_local(self):
        client=self.app.test_client()
        with client.session_transaction() as session:session.update(user_id=1,role='user')
        check=DocumentCheck.query.first();check.data_classification='open';db.session.commit()
        with patch('app.gemini_enabled',return_value=False), patch('app.score_with_gemini') as gemini, patch('app.score_with_local_model') as local:
            self.assertEqual(client.post(f'/check/{check.id}/run-compliance').status_code,302)
            gemini.assert_not_called();local.assert_not_called()
