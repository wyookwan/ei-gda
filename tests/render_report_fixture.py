import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_report import ReportTests
fixture=ReportTests()
fixture.setUp()
try:
    check=fixture.populate_report()
    response=fixture.client().get(f'/check/{check.id}')
    assert response.status_code==200
    Path(sys.argv[1]).write_bytes(response.data)
finally:
    fixture.tearDown()
