import threading

from hp3458a_studio.drivers import gpib_bus_lock


def test_gpib_devices_share_bus_but_lan_and_usb_devices_are_independent():
    assert gpib_bus_lock("GPIB0::21::INSTR") is gpib_bus_lock("gpib0::22::instr")
    assert gpib_bus_lock("GPIB0::21::INSTR") is not gpib_bus_lock("GPIB1::21::INSTR")
    for first, second in (
        ("TCPIP0::192.0.2.1::INSTR", "TCPIP0::192.0.2.2::INSTR"),
        ("USB0::DMM1::INSTR", "USB0::DMM2::INSTR"),
    ):
        acquired = threading.Event()

        def independent_read(resource=second, event=acquired):
            with gpib_bus_lock(resource):
                event.set()

        with gpib_bus_lock(first):
            worker = threading.Thread(target=independent_read)
            worker.start()
            overlapped = acquired.wait(1)
        worker.join(1)
        assert overlapped, "Independent devices must not block behind another read"
        assert not worker.is_alive()
