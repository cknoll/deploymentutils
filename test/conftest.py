import ipydex

def pytest_runtest_setup(item):
    print("This invocation of pytest is customized")


def pytest_exception_interact(node, call, report):
    # If an exception occurred during a test run, open an interactive shell in the context where the exception occurred.

    # debug code:
    # tb = call.excinfo.tb
    # tb_frame_list = []
    # while tb.tb_next is not None:
    #     tb_frame_list.append(tb.tb_frame)
    #     tb = tb.tb_next

    # critical_frame = tb.tb_frame
    # tb_frame_list.append(critical_frame)

    # tb_frame_list.reverse()


    # ipydex.IPS()
    # exc_type, exc_value, tb = call.excinfo.type, ...
    ipydex.ips_excepthook(call.excinfo.type, call.excinfo.value, call.excinfo.tb, frame_upcount=0)
