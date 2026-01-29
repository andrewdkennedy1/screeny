import unittest
from hdmi_control.ddc.parser import parse_getvcp, parse_detect


class TestDdcParser(unittest.TestCase):
    def test_parse_getvcp(self):
        out = "VCP code 0x10 (Brightness): current value = 40, max value = 100"
        val = parse_getvcp(out, "10")
        self.assertEqual(val.cur, 40)
        self.assertEqual(val.max, 100)

    def test_parse_detect(self):
        out = """
Display 1
   I2C bus: /dev/i2c-3
   EDID synopsis: DEL 0x1234
   Model: U2720Q
   Serial number: 98765
"""
        displays = parse_detect(out)
        self.assertEqual(len(displays), 1)
        self.assertEqual(displays[0]["bus"], "/dev/i2c-3")


if __name__ == "__main__":
    unittest.main()
