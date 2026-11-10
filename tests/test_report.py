import unittest
import test_international_catalog as fixtures
from extensions import db
from models import DocumentCheck, Standard
from utils import json_dumps


class ReportTests(unittest.TestCase):
    setUp = fixtures.CatalogTests.setUp
    tearDown = fixtures.CatalogTests.tearDown

    def populate_report(self):
        check = DocumentCheck.query.first()
        rows = [dict(standard=f'REF{i % 13}', item_code=f'ITEM{i}', title=f'Item {i}',
                     category=f'Category {i % 14}', score=i % 6, maturity='Defined',
                     reason=f'Reason {i}', gap=f'Gap {i}', recommendation=f'Recommendation {i}',
                     evidence=[dict(filename='evidence.pdf',page=i+1,file_id=1,snippet=f'Full evidence {i}')]) for i in range(43)]
        rows[0].update(title='<img src=x onerror=alert(1)>',score=None,evidence=[])
        check.compliance_results_json=json_dumps(rows)
        check.selected_standard_ids_json=json_dumps([Standard.query.first().id])
        db.session.commit()
        return check

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=1,role='user')
        return client

    def test_report_full_payload_and_empty_state_render(self):
        check=self.populate_report()
        response=self.client().get(f'/check/{check.id}')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        for marker in ['report-results-json','ITEM42','Full evidence 42','report-context','reportChartView']:
            self.assertIn(marker,html)
        self.assertNotIn('<img src=x onerror=alert(1)>',html)
        check.compliance_results_json='[]';db.session.commit()
        self.assertEqual(self.client().get(f'/check/{check.id}').status_code,200)

    def test_upload_requires_acknowledgment_matching_classification(self):
        client=self.client()
        for classification,ack in [('open',''),('confidential','open'),('open','confidential')]:
            response=client.post('/upload',data={'data_classification':classification,'classification_acknowledged':ack})
            self.assertEqual(response.status_code,302)
            with client.session_transaction() as session:
                self.assertIn('กดรับทราบ',session['_flashes'][-1][1])
        self.assertEqual(DocumentCheck.query.count(),1)


if __name__ == '__main__':
    unittest.main()
