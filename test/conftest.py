import ipydex
import pytest

def pytest_runtest_setup(item):
    print("This invocation of pytest is customized")


def pytest_exception_interact(node, call, report):
    ipydex.ips_excepthook(call.excinfo.type, call.excinfo.value, call.excinfo.tb, frame_upcount=0)


def pytest_addoption(parser):
    parser.addoption("--no-remote", action="store_true", help="omit tests that require remote execution")

def pytest_configure(config):
    config.addinivalue_line("markers", "requires_remote: mark test as requires remote execution")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--no-remote"):
        skip_remote = pytest.mark.skip(reason="this test requires remote execution")
        for item in items:
            if "requires_remote" in item.keywords:
                item.add_marker(skip_remote)
    else:
        # option not given
        pass


@pytest.fixture
def no_parallel(request):
    return request.config.getoption("--no-remote")
