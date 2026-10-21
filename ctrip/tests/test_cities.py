"""内置城市表测试。"""
from ctrip.cities import CITIES
from ctrip.models import City


def test_cities_are_models():
    assert isinstance(CITIES["SZX"], City)
    assert CITIES["SZX"] == City(code="SZX", name="深圳", id="30")
    assert CITIES["CAN"].name == "广州"
    assert len(CITIES) >= 30


def test_known_city_codes_not_airport_codes():
    """城市码约定:北京 BJS / 西安 SIA / 成都 CTU(不是机场码)。"""
    assert CITIES["BJS"].name == "北京"
    assert CITIES["SIA"].name == "西安"
    assert CITIES["CTU"].name == "成都"
    assert "PEK" not in CITIES
