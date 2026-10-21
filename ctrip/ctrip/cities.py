#!/usr/bin/env python3
"""常用城市三字码 → City(code, name, cityId)。

来自 airportFuzzySearch 抓取(2026-10-20)。注意用城市码,不是机场码:
北京=BJS(非PEK)、成都=CTU(非TFU)、西安=SIA(非XIY)、上海=SHA/PVG 都映射到 SHA。
未知城市走 CtripClient.city() 动态查询并缓存到 ~/.ctrip_cities.json。
"""
from typing import Dict

from .models import City

CITIES: Dict[str, City] = {c.code: c for c in [
    City(code="BJS", name="北京", id="1"),
    City(code="SHA", name="上海", id="2"),
    City(code="TSN", name="天津", id="3"),
    City(code="CKG", name="重庆", id="4"),
    City(code="HRB", name="哈尔滨", id="5"),
    City(code="DLC", name="大连", id="6"),
    City(code="TAO", name="青岛", id="7"),
    City(code="NKG", name="南京", id="12"),
    City(code="WUX", name="无锡", id="13"),
    City(code="SIA", name="西安", id="10"),
    City(code="HGH", name="杭州", id="17"),
    City(code="XMN", name="厦门", id="25"),
    City(code="HFE", name="合肥", id="278"),
    City(code="CTU", name="成都", id="28"),
    City(code="SZX", name="深圳", id="30"),
    City(code="CAN", name="广州", id="32"),
    City(code="KWL", name="桂林", id="33"),
    City(code="KMG", name="昆明", id="34"),
    City(code="URC", name="乌鲁木齐", id="39"),
    City(code="HAK", name="海口", id="42"),
    City(code="SYX", name="三亚", id="43"),
    City(code="CGQ", name="长春", id="158"),
    City(code="LHW", name="兰州", id="100"),
    City(code="INC", name="银川", id="99"),
    City(code="HET", name="呼和浩特", id="103"),
    City(code="SWA", name="揭阳", id="956"),
    City(code="SHE", name="沈阳", id="451"),
    City(code="WUH", name="武汉", id="477"),
    City(code="NGB", name="宁波", id="375"),
    City(code="FOC", name="福州", id="258"),
    City(code="JJN", name="泉州", id="406"),
    City(code="KOW", name="赣州", id="268"),
    City(code="LYA", name="洛阳", id="350"),
    City(code="KHN", name="南昌", id="376"),
    City(code="NNG", name="南宁", id="380"),
    City(code="CSX", name="长沙", id="206"),
    City(code="KWE", name="贵阳", id="38"),
]}
