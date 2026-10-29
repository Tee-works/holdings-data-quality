from datetime import UTC, date, datetime

import pytest

from hdq import check, load, sample
from hdq.config import Settings
from hdq.load import connect

RUN_AT = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    s = Settings.from_env(base=tmp_path_factory.mktemp("hdq"), sample=True)
    sample.write_sample(s.raw_dir)
    load.build(s)
    return s


@pytest.fixture(scope="session")
def run(settings):
    return check.run(settings, today=date(2026, 10, 26), now=RUN_AT)


@pytest.fixture()
def con(settings):
    c = connect(settings.warehouse)
    yield c
    c.close()
